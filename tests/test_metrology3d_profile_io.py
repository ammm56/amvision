"""B07 标准 NPZ 严格读取，文件数组与内核使用同一结构和标定。"""

from io import BytesIO
from zipfile import ZipFile
import weakref

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from custom_nodes.metrology3d_nodes.shared.io.profile_file import borrow_profile_file
from tests.point_cloud_support import policy
from tests.test_metrology3d_profile_conversion import inputs, specification, execute


def encode(arrays, compressed=False):
    """成熟 NumPy 写出，测试不手写 NPZ 解析。"""
    stream = BytesIO()
    writer = np.savez_compressed if compressed else np.savez
    writer(stream, **arrays)
    return stream.getvalue()


def read(data, spec=None, *, p=None, has_validity=False, cancel=lambda: None):
    """借用期间检查原字段，退出不得继续持有映射或预算。"""
    p = p or policy(max_working_bytes=4 * 1024**2, max_live_array_bytes=8 * 1024**2)
    budget = CloudArrayBudget(p.max_live_array_bytes)
    exposed = None
    try:
        with borrow_profile_file(
            BytesIO(data),
            spec or specification(),
            has_validity=has_validity,
            policy=p,
            budget=budget,
            cancel=cancel,
        ) as exposed:
            assert all(not a.flags.writeable for a in exposed.values())
            copied = {k: a.copy() for k, a in exposed.items()}
        assert not exposed
        return copied
    finally:
        assert budget.used == 0


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
@pytest.mark.parametrize("order", ["C", "F"])
def test_lossless_npz_file_to_same_projection(compressed, dtype, order):
    arrays = inputs(dtype, [12, 3, 8, 8])
    arrays["profiles"] = np.array(
        arrays["profiles"], dtype=np.dtype(dtype).newbyteorder(">"), order=order
    )
    arrays["validity"] = np.array([1, 0, 1, 1, 1, 1], dtype="uint8")
    spec = specification(
        dtype=dtype,
        displacement=dict(
            kind="encoder-positions", dtype="float64", scale=0.5, origin=10
        ),
    )
    loaded = read(encode(arrays, compressed), spec, has_validity=True)
    for name, array in arrays.items():
        np.testing.assert_array_equal(loaded[name], array)
        assert loaded[name].dtype.name == array.dtype.name
        loaded[name].setflags(write=False)
    points, counts = execute(loaded, spec)
    assert counts["valid"] == 5 and len(points["positions"]) == 6


@pytest.mark.parametrize(
    "fault", ["missing", "extra", "object", "precision", "shape", "offset", "mask"]
)
def test_reject_bad_or_omitted_fields(fault):
    arrays = inputs()
    if fault == "missing":
        arrays.pop("line_ids")
    elif fault == "extra":
        arrays["unexpected"] = np.array([1])
    elif fault == "object":
        arrays["profiles"] = np.array([[object(), object()]] * 6, dtype=object)
    elif fault == "precision":
        arrays["profiles"] = arrays["profiles"].astype("float64")
    elif fault == "shape":
        arrays["profiles"] = arrays["profiles"].reshape(3, 4)
    elif fault == "offset":
        arrays["line_offsets"] = np.array([0, 3, 2, 5, 6], dtype="uint64")
    elif fault == "mask":
        arrays["validity"] = np.array([1, 0, 1, 1, 2, 1], dtype="uint8")
    with pytest.raises(InvalidRequestError):
        read(encode(arrays), has_validity=fault == "mask")


@pytest.mark.parametrize(
    "fault",
    ["truncated-zip", "truncated-npy", "trailing-npy", "duplicate", "corrupt-crc"],
)
def test_reject_corrupt_archive_and_member_records(fault):
    good = encode(inputs())
    if fault == "truncated-zip":
        broken = good[:-16]
    elif fault == "corrupt-crc":
        index = good.index(b"\x00\x00\x80\x3f\x00\x00\x00\x40")
        broken = good[:index] + bytes([good[index] ^ 1]) + good[index + 1 :]
    else:
        output = BytesIO()
        with ZipFile(BytesIO(good)) as source, ZipFile(output, "w") as target:
            for name in source.namelist():
                content = source.read(name)
                if name == "profiles.npy":
                    if fault == "truncated-npy":
                        content = content[:-1]
                    elif fault == "trailing-npy":
                        content += b"extra"
                target.writestr(name, content)
            if fault == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate"):
                    target.writestr("profiles.npy", source.read("profiles.npy"))
        broken = output.getvalue()
    with pytest.raises(InvalidRequestError):
        read(broken)


@pytest.mark.parametrize("stop", [1, 3, 8, 18, 30, 45])
def test_cancel_releases_npz_arrays_and_budget(stop):
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == stop:
            raise InterruptedError("cancel NPZ")

    with pytest.raises(InterruptedError):
        read(encode(inputs(), True), cancel=cancel)


def test_metadata_budget_and_zip_directory_bounds():
    with pytest.raises(InvalidRequestError):
        read(encode(inputs()), p=policy())
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("unexpected" * 2000, b"")
    with pytest.raises(InvalidRequestError):
        read(stream.getvalue())


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("chunk_bytes", [256, 262144])
def test_member_body_can_exceed_directory_read_limit(compressed, chunk_bytes):
    """目录边界保持严格；正文大于 ZIP 尾目录窗口时仍分块无损读取。"""
    count = 25000
    arrays = dict(
        profiles=np.arange(count * 2, dtype="float64").reshape(count, 2) / 7,
        line_offsets=np.array([0, count], dtype="uint64"),
        line_ids=np.array([9], dtype="uint64"),
    )
    spec = specification(point_count=count, profile_count=1, dtype="float64")
    p = policy(
        max_decoded_bytes=1024**2,
        max_working_bytes=8 * 1024**2,
        max_live_array_bytes=16 * 1024**2,
        chunk_rows=2048,
        chunk_bytes=chunk_bytes,
    )
    loaded = read(encode(arrays, compressed), spec, p=p)
    for name in arrays:
        assert loaded[name].tobytes() == arrays[name].tobytes()


def test_larger_numeric_npz_preserves_endian_and_last_record():
    count = 20_000
    spec = specification(point_count=count, profile_count=2)
    arrays = dict(
        profiles=np.arange(count * 2, dtype=">f4").reshape(count, 2),
        line_offsets=np.array([0, 7, count], dtype="<u8"),
        line_ids=np.array([3, 8], dtype="<u8"),
    )
    actual = read(
        encode(arrays),
        spec,
        p=policy(
            max_decoded_bytes=1024**2,
            max_working_bytes=4 * 1024**2,
            max_live_array_bytes=8 * 1024**2,
        ),
    )
    for key in arrays:
        np.testing.assert_array_equal(actual[key], arrays[key])


def test_consumer_error_keeps_its_type_and_releases_aliases():
    p = policy(max_working_bytes=4 * 1024**2, max_live_array_bytes=8 * 1024**2)
    budget = CloudArrayBudget(p.max_live_array_bytes)
    error = ValueError("downstream error")
    with pytest.raises(ValueError) as caught:
        with borrow_profile_file(
            BytesIO(encode(inputs())),
            specification(),
            has_validity=False,
            policy=p,
            budget=budget,
            cancel=lambda: None,
        ) as arrays:
            refs = [weakref.ref(a) for a in arrays.values()]
            raise error
    assert caught.value is error
    assert not arrays and all(ref() is None for ref in refs)
    assert budget.used == 0
