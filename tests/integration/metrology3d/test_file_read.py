"""真实 ObjectStore 到规范点属性的读取、故障与资源验证。"""

from io import BytesIO
import struct
import weakref

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError, WorkflowInputError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_cloud_file
from tests.point_cloud_support import options, policy


def publish(storage, content):
    """真实不可变对象，不用 fake success storage。"""
    metadata = storage.write_immutable_stream(
        object_prefix="projects/test/results/cloud",
        source_stream=BytesIO(content),
        media_type="application/octet-stream",
        extension="bin",
    ).metadata
    return {
        "transport_kind": "storage",
        "storage_ref": "object-store",
        "object_key": metadata.object_key,
        "file_name": "cloud.bin",
        "media_type": metadata.media_type,
        "content_length": metadata.content_length,
        "checksum_algorithm": "sha256",
        "checksum": metadata.checksum,
        "immutable_version": metadata.immutable_version,
    }


def ply(
    body=b"0 -0 3\n4 5 6\n",
    fields="property float x\nproperty float y\nproperty float z\n",
    encoding="ascii",
    count=2,
):
    """独立生成已知格式夹具，不用被测 writer 定义期望。"""
    return (
        f"ply\nformat {encoding} 1.0\nelement vertex {count}\n{fields}end_header\n".encode()
        + body
    )


@pytest.fixture
def context(tmp_path):
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    limits = policy()
    budget = CloudArrayBudget(limits.max_live_array_bytes)
    scope = ResourceScope(kind="workflow")
    yield storage, limits, budget, scope
    assert scope.close() == ()
    assert budget.used == 0


def run(context, content, opts=None, cancel=lambda: None, **kwargs):
    storage, limits, budget, scope = context
    return read_cloud_file(
        object_store=storage,
        project_id="test",
        file=publish(storage, content),
        options=opts or options(),
        policy=limits,
        budget=budget,
        scope=scope,
        cancel=cancel,
        **kwargs,
    )


@pytest.mark.parametrize(
    "profile,encoding,endian",
    [
        ("ply-ascii", "ascii", None),
        ("ply-binary-le", "binary_little_endian", "<"),
        ("ply-binary-be", "binary_big_endian", ">"),
    ],
)
def test_ply_precision_order_and_close(context, profile, encoding, endian):
    content = (
        ply(encoding=encoding)
        if endian is None
        else ply(struct.pack(endian + "6f", 0, -0.0, 3, 4, 5, 6), encoding=encoding)
    )
    value = run(context, content, options(profile))
    assert value.point_count == 2 and value.non_finite_positions == 0
    with value.arrays.borrow() as arrays:
        assert arrays["positions"].dtype == np.dtype("<f4")
        np.testing.assert_array_equal(arrays["positions"], [[0, -0.0, 3], [4, 5, 6]])
        assert np.signbit(arrays["positions"][0, 1])
    assert context[2].used == 24


@pytest.mark.parametrize(
    "body",
    [
        b"1 2 3\n",
        b"1 2\n4 5 6\n",
        b"1 2 3 4\n4 5 6\n",
        b"1 bad 3\n4 5 6\n",
        b"1 2 3\n4 5 6\n7 8 9\n",
        b"1e999 2 3\n4 5 6\n",
    ],
)
def test_bad_files_never_publish_arrays(context, body):
    with pytest.raises(WorkflowInputError) as error:
        run(context, ply(body))
    assert error.value.code == "workflow_input_point_cloud_data_invalid"
    assert context[2].used == 0 and context[3].resource_count == 0


def test_unmapped_fields_and_dtype_narrowing_rejected(context):
    extra = (
        "property float x\nproperty float y\nproperty float z\nproperty uint label\n"
    )
    with pytest.raises(WorkflowInputError, match="完整覆盖"):
        run(context, ply(b"1 2 3 4\n5 6 7 8\n", fields=extra))
    with pytest.raises(WorkflowInputError, match="类型"):
        run(context, ply(), options(dtype="float64"))


def test_nonfinite_values_preserved_not_zeroed(context):
    result = run(context, ply(b"nan inf -inf\n0 0 0\n"))
    assert result.non_finite_positions == 1
    with result.arrays.borrow() as data:
        assert np.isnan(data["positions"][0, 0])
        assert np.isposinf(data["positions"][0, 1])
        np.testing.assert_array_equal(data["positions"][1], [0, 0, 0])


def test_actual_checksum_not_just_sidecar(context):
    storage, limits, budget, scope = context
    ref = publish(storage, ply())
    storage.resolve(ref["object_key"]).write_bytes(ply(b"0 -0 9\n4 5 6\n"))
    with pytest.raises(InvalidRequestError, match="摘要"):
        read_cloud_file(
            object_store=storage,
            project_id="test",
            file=ref,
            options=options(),
            policy=limits,
            budget=budget,
            scope=scope,
            cancel=lambda: None,
        )
    assert budget.used == 0


def test_project_scope_and_wrong_profile(context):
    storage, limits, budget, scope = context
    ref = publish(storage, ply())
    with pytest.raises(WorkflowInputError):
        read_cloud_file(
            object_store=storage,
            project_id="other",
            file=ref,
            options=options(),
            policy=limits,
            budget=budget,
            scope=scope,
            cancel=lambda: None,
        )
    with pytest.raises(WorkflowInputError, match="编码") as error:
        run(context, ply(), options("ply-binary-le"))
    assert error.value.code == "workflow_input_point_cloud_format_mismatch"
    assert error.value.details["actual_encoding"] == "ascii"


def test_cancel_after_decode_and_before_registration_releases(context):
    for stop in range(1, 18):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == stop:
                raise InterruptedError("cancel fixture")

        try:
            result = run(context, ply(), cancel=cancel)
            result.arrays.close()
        except InterruptedError:
            pass
        assert context[2].used == 0


def test_pcd_organization_and_uint64(context):
    fields = (
        {
            "source_names": ["label"],
            "target_name": "label",
            "semantic": "scalar",
            "dtype": "uint64",
            "components": 1,
            "unit": "1",
        },
    )
    raw = (
        "VERSION .7\nFIELDS x y z label\nSIZE 4 4 4 8\nTYPE F F F U\nCOUNT 1 1 1 1\n"
        "WIDTH 1\nHEIGHT 2\nVIEWPOINT 1 2 3 1 0 0 0\nPOINTS 2\nDATA ascii\n"
        "1 2 3 18446744073709551615\n4 5 6 7\n"
    ).encode()
    value = run(context, raw, options("pcd-ascii", extra=fields))
    assert value.source_metadata.organized
    assert value.source_metadata.source_spatial == value.spatial
    assert value.source_metadata.viewpoint[:3] == (1, 2, 3)
    with value.arrays.borrow() as arrays:
        assert int(arrays["label"][0, 0]) == 2**64 - 1


@pytest.mark.parametrize(
    "body",
    [
        b"1 2\n",
        b"1 2 3 4\n",
        b"1,2 3 4\n",
        b"# header\n1 2 3\n",
        b"1 bad 3\n",
        b"1e999 2 3\n",
        b"1e-999 2 3\n",
        b"1e50 2 3\n",
        b"1\r2 3\n",
        b"1 2 3\r",
    ],
)
def test_xyz_rejects_bad_rows(context, body):
    with pytest.raises(WorkflowInputError):
        run(context, body, options("xyz-whitespace"))
    assert context[2].used == 0


def test_xyz_multiblock_whitespace_and_float64(context):
    value = run(
        context,
        b"\r\n1\t2 3\r\n\n4 5 6\n7 8 9\n10 11 12",
        options("xyz-whitespace", "float64"),
    )
    with value.arrays.borrow() as arrays:
        assert arrays["positions"].dtype == np.dtype("float64")
        np.testing.assert_array_equal(
            arrays["positions"], np.arange(1, 13).reshape(4, 3)
        )


def test_budget_admission_counts_source_and_destination(context):
    storage, _limits, _budget, scope = context
    limits = policy(max_decoded_bytes=32, max_live_array_bytes=32)
    budget = CloudArrayBudget(32)
    with pytest.raises(InvalidRequestError, match="预算"):
        read_cloud_file(
            object_store=storage,
            project_id="test",
            file=publish(storage, ply()),
            options=options(),
            policy=limits,
            budget=budget,
            scope=scope,
            cancel=lambda: None,
        )
    assert budget.used == 0


def test_retained_failure_does_not_retain_decoded_arrays(context, monkeypatch):
    """异常被上层保存时也不能把 decoder 的完整数组留在 traceback。"""
    allocate = np.empty
    references = []

    def traced(*args, **kwargs):
        result = allocate(*args, **kwargs)
        references.append(weakref.ref(result))
        return result

    monkeypatch.setattr(np, "empty", traced)
    with pytest.raises(WorkflowInputError) as failure:
        run(context, ply(b"1 2 3\nbad 4 5\n"))
    assert failure.value is not None
    assert references and all(reference() is None for reference in references)
    assert context[2].used == 0


@pytest.mark.parametrize(
    "profile,extra,body,expected",
    [
        (
            "xyzn-whitespace",
            {
                "source_names": ["nx", "ny", "nz"],
                "target_name": "normals",
                "semantic": "normal",
                "dtype": "float32",
                "components": 3,
                "unit": "1",
            },
            b"1 2 3 0 0 2\n",
            [0, 0, 2],
        ),
        (
            "xyzi-whitespace",
            {
                "source_names": ["intensity"],
                "target_name": "intensity",
                "semantic": "scalar",
                "dtype": "float64",
                "components": 1,
                "unit": None,
            },
            b"1 2 3 0.12345678901234567\n",
            [0.12345678901234567],
        ),
        (
            "xyzrgb-whitespace",
            {
                "source_names": ["r", "g", "b"],
                "target_name": "colors",
                "semantic": "color-rgb",
                "dtype": "uint8",
                "components": 3,
                "unit": "1",
            },
            b"1 2 3 0 127 255\n",
            [0, 127, 255],
        ),
    ],
)
def test_xyz_profiles_preserve_declared_attributes(
    context, profile, extra, body, expected
):
    result = run(context, body, options(profile, extra=(extra,)))
    with result.arrays.borrow() as arrays:
        assert arrays[extra["target_name"]].dtype == np.dtype(extra["dtype"])
        np.testing.assert_array_equal(arrays[extra["target_name"]][0], expected)


@pytest.mark.parametrize(
    "color", [b"-1 0 0", b"256 0 0", b"0.5 0 0", b"nan 0 0", b"inf 0 0"]
)
def test_xyz_rgb_rejects_lossy_quantization(context, color):
    extra = {
        "source_names": ["r", "g", "b"],
        "target_name": "colors",
        "semantic": "color-rgb",
        "dtype": "uint8",
        "components": 3,
        "unit": "1",
    }
    with pytest.raises(WorkflowInputError) as error:
        run(
            context,
            b"1 2 3 " + color + b"\n",
            options("xyzrgb-whitespace", extra=(extra,)),
        )
    assert "RGB" in error.value.details["parser_error"]


@pytest.mark.parametrize("compressed", [False, True])
def test_pcd_binary_encodings_and_count_fields(context, compressed):
    import lzf

    header = (
        "VERSION .7\nFIELDS x y z normals\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 3\n"
        "WIDTH 2\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS 2\nDATA "
    )
    if compressed:
        # PCL 的原 FIELDS 分组：法向 COUNT 分量在每点内相邻。
        data = struct.pack("<12f", 1, 4, 2, 5, 3, 6, 0, 0, 2, 0, 0, 3)
        encoded = lzf.compress(data)
        assert encoded
        body = struct.pack("<II", len(encoded), len(data)) + encoded
        encoding = "binary_compressed"
        profile = "pcd-binary-compressed"
    else:
        body = struct.pack("<12f", 1, 2, 3, 0, 0, 2, 4, 5, 6, 0, 0, 3)
        encoding = "binary"
        profile = "pcd-binary"
    from pypcd4 import MetaData

    # 名称展开由成熟库的公开 metadata 给出，不在平台重复实现 COUNT 解析。
    metadata = MetaData.parse_header((header + encoding + "\n").splitlines())
    extra = {
        "source_names": metadata.field_columns[-1],
        "target_name": "normals",
        "semantic": "normal",
        "dtype": "float32",
        "components": 3,
        "unit": "1",
    }
    result = run(
        context,
        (header + encoding + "\n").encode() + body,
        options(profile, extra=(extra,)),
    )
    with result.arrays.borrow() as arrays:
        np.testing.assert_array_equal(arrays["positions"], [[1, 2, 3], [4, 5, 6]])
        np.testing.assert_array_equal(arrays["normals"], [[0, 0, 2], [0, 0, 3]])


def test_declared_double_keeps_adjacent_values(context):
    first = np.float64(1)
    second = np.nextafter(first, np.float64(2))
    content = ply(
        struct.pack("<6d", first, 0, 0, second, 0, 0),
        fields="property double x\nproperty double y\nproperty double z\n",
        encoding="binary_little_endian",
    )
    result = run(context, content, options("ply-binary-le", "float64"))
    with result.arrays.borrow() as arrays:
        assert arrays["positions"][1, 0] > arrays["positions"][0, 0]
        assert arrays["positions"][1, 0] == second


def test_scope_closed_during_decode_cannot_publish_result(context, monkeypatch):
    """解析期间运行结束时，登记失败必须收回全部数组，不返回失效结果。"""
    scope = context[3]
    register = scope.register

    def late_register(*args, **kwargs):
        assert scope.close() == ()
        register(*args, **kwargs)

    monkeypatch.setattr(scope, "register", late_register)
    with pytest.raises(RuntimeError, match="已关闭"):
        run(context, ply())
    assert context[2].used == 0 and scope.resource_count == 0


@pytest.mark.parametrize("fail_at", [1, 2])
def test_array_allocation_failure_returns_reservation(context, monkeypatch, fail_at):
    """源解码或规范属性分配失败都不留下容量预留。"""
    allocate = np.empty
    calls = 0

    def failing_allocate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise MemoryError("allocation fixture")
        return allocate(*args, **kwargs)

    monkeypatch.setattr(np, "empty", failing_allocate)
    with pytest.raises(MemoryError, match="allocation fixture"):
        run(context, ply())
    assert context[2].used == 0 and context[3].resource_count == 0
