"""受控交换导出与资产恢复的真实解析验证。"""

from io import BytesIO
from hashlib import sha256

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CloudAssetPolicy,
)
from custom_nodes._metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes._metrology3d_nodes.shared.io.export_file import (
    CloudExportOptions,
    export_cloud_file,
)
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes._metrology3d_nodes.shared.io.formats import inspect_cloud_file
from tests.point_cloud_support import options, policy, create_resource_service
from tests.test_metrology3d_preprocess import make_cloud
from tests.integration.metrology3d.test_file_read import publish, ply
from backend.contracts.workflows.point_cloud import CloudField
from backend.contracts.workflows.point_cloud_runtime import (
    CloudLocalSource,
    FilterCloudValid,
)
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from tests.test_point_cloud_runtime import own
from tests.point_cloud_support import spatial


PROFILES = (
    "ply-ascii",
    "ply-binary-le",
    "ply-binary-be",
    "pcd-ascii",
    "pcd-binary",
    "pcd-binary-compressed",
    "xyz-whitespace",
)
service = pytest.fixture(name="service")(create_resource_service)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("dtype", ("float32", "float64"))
def test_exchange_keeps_all_declared_values(profile, dtype):
    """文本与二进制均保持源 dtype 和数值，不以近似容差掩盖窄化。"""
    expected = np.array(
        [[1.234567891234, -0.0, 100000.123456789], [3, np.nan, np.inf]], dtype=dtype
    )
    scope, runtime, cloud = make_cloud(coordinates=expected)
    initial = runtime.budget.used
    try:
        stream = BytesIO()
        summary, read_options = export_cloud_file(
            runtime,
            cloud,
            CloudExportOptions(
                profile_id=profile,
                profile_version=1,
                fields=("positions",),
                file_name="export.bin",
                spatial_acknowledged=True,
            ),
            stream=stream,
            max_output_bytes=4096,
            cancel=lambda: None,
        )
        assert runtime.budget.used == initial
        stream.seek(0)
        inspected = inspect_cloud_file(stream, read_options, policy(), lambda: None)
        result = inspected.read()
        for i, name in enumerate(("x", "y", "z")):
            assert result.dtype[name].newbyteorder("=") == np.dtype(dtype)
            np.testing.assert_array_equal(result[name], expected[:, i])
        assert summary["fields_written"] == ["positions"]
        assert summary["fields_omitted"] == []
    finally:
        assert scope.close() == ()


def test_original_file_asset_reuses_complete_strict_reader(service):
    """原件先解析，再逐字节保存，资源重读沿同一个严格文件入口。"""
    data = ply()
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="source", policy=policy())
    other = ResourceScope(kind="test")
    target = get_cloud_runtime(other, run_id="target", policy=policy())
    limits = CloudAssetPolicy(
        max_asset_bytes=8192, max_archive_bytes=16384, chunk_bytes=128
    )
    try:
        ref = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=publish(service.storage, data),
            options=options(),
            cancel=lambda: None,
        )
        saved = save_cloud(
            runtime,
            ref,
            service=service,
            project_id="test",
            name="Original",
            mode="original",
            write_identity="f" * 64,
            policy=limits,
            cancel=lambda: None,
        )
        doc = service.read(saved, project_id="test")
        assert doc.content.point_cloud.blobs[0].sha256 == sha256(data).hexdigest()
        restored = read_asset(
            target,
            saved,
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        with runtime.borrow(ref) as expected, target.borrow(restored) as actual:
            assert (
                expected.chunk(0, 2)["positions"].tobytes()
                == actual.chunk(0, 2)["positions"].tobytes()
            )
    finally:
        assert not scope.close()
        assert not other.close()


def test_export_cancellation_capacity_short_write_and_unsupported_field():
    """失败输出不返回成功摘要，临时结构数组预算归还。"""
    scope, runtime, cloud = make_cloud(
        attributes=[("serial", np.array([2**64 - 1, 7], dtype="<u8"), None)]
    )
    initial = runtime.budget.used
    params = CloudExportOptions(
        profile_id="ply-binary-le",
        profile_version=1,
        fields=("positions", "serial"),
        file_name="export.ply",
        spatial_acknowledged=True,
    )
    try:
        with pytest.raises(InvalidRequestError, match="不存在"):
            export_cloud_file(
                runtime,
                cloud,
                params.model_copy(update={"fields": ("positions", "missing")}),
                stream=BytesIO(),
                max_output_bytes=4096,
                cancel=lambda: None,
            )
        assert runtime.budget.used == initial
        params = params.model_copy(update={"fields": ("positions",)})
        with pytest.raises(InvalidRequestError, match="限额"):
            export_cloud_file(
                runtime,
                cloud,
                params,
                stream=BytesIO(),
                max_output_bytes=8,
                cancel=lambda: None,
            )
        assert runtime.budget.used == initial

        class Short(BytesIO):
            def write(self, data):
                return max(0, len(data) - 1)

        with pytest.raises(OSError, match="短写"):
            export_cloud_file(
                runtime,
                cloud,
                params,
                stream=Short(),
                max_output_bytes=4096,
                cancel=lambda: None,
            )
        assert runtime.budget.used == initial

        def cancel():
            raise RuntimeError("cancel")

        with pytest.raises(RuntimeError, match="cancel"):
            export_cloud_file(
                runtime,
                cloud,
                params,
                stream=BytesIO(),
                max_output_bytes=4096,
                cancel=cancel,
            )
        assert runtime.budget.used == initial
    finally:
        assert not scope.close()


@pytest.mark.parametrize(
    "profile",
    (*PROFILES[:-1], "xyzn-whitespace", "xyzi-whitespace", "xyzrgb-whitespace"),
)
def test_export_attributes_and_explicit_omissions(profile):
    """法线、颜色及混合精度标量逐字段重读，未选择字段明确列出。"""
    arrays = {
        "positions": np.array([[1, 2, 3], [4, 5, 6]], dtype="<f4"),
        "normals": np.array([[0.1, 0.2, 0.3], [-0.0, 1, -1]], dtype="<f8"),
        "colors": np.array([[0, 127, 255], [255, 2, 0]], dtype="u1"),
        "intensity": np.array([[1.234567890123], [-0.0]], dtype="<f8"),
    }
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="attributes", policy=policy())
    fields = tuple(
        CloudField(
            name=name,
            semantic=semantic,
            dtype=arrays[name].dtype.name,
            components=arrays[name].shape[1],
            unit=unit,
        )
        for name, semantic, unit in (
            ("positions", "position", None),
            ("normals", "normal", "1"),
            ("colors", "color-rgb", "1"),
            ("intensity", "scalar", None),
        )
    )
    cloud = runtime.register_source(
        owner=own(runtime, arrays),
        point_count=2,
        fields=fields,
        spatial=spatial(),
        source=CloudLocalSource(
            kind="local-array",
            content_sha256="1" * 64,
            descriptor_sha256="2" * 64,
            source_observation_id=None,
        ),
        source_metadata=None,
        cancel=lambda: None,
    )
    selected = {
        "xyzn-whitespace": ("positions", "normals"),
        "xyzi-whitespace": ("positions", "intensity"),
        "xyzrgb-whitespace": ("positions", "colors"),
    }.get(profile, tuple(arrays))
    try:
        stream = BytesIO()
        summary, options = export_cloud_file(
            runtime,
            cloud,
            CloudExportOptions(
                profile_id=profile,
                profile_version=1,
                fields=selected,
                file_name="attributes.bin",
                spatial_acknowledged=True,
            ),
            stream=stream,
            max_output_bytes=8192,
            cancel=lambda: None,
        )
        stream.seek(0)
        result = inspect_cloud_file(stream, options, policy(), lambda: None).read()
        for field in options.field_mapping:
            for i, column in enumerate(field.source_names):
                actual = result[column].astype(arrays[field.target_name].dtype)
                assert actual.tobytes() == arrays[field.target_name][:, i].tobytes()
        assert summary["fields_omitted"] == [f for f in arrays if f not in selected]
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("profile", PROFILES)
def test_empty_derived_cloud_export(profile):
    """零点派生云可以交换导出，不能伪造一个输入点或改变声明字段。"""
    scope, runtime, cloud = make_cloud(
        attributes=[("validity", np.zeros(2, dtype="u1"), "1")]
    )
    try:
        empty, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        stream = BytesIO()
        summary, options = export_cloud_file(
            runtime,
            empty,
            CloudExportOptions(
                profile_id=profile,
                profile_version=1,
                fields=("positions",),
                file_name="empty.bin",
                spatial_acknowledged=True,
            ),
            stream=stream,
            max_output_bytes=4096,
            cancel=lambda: None,
        )
        stream.seek(0)
        inspected = inspect_cloud_file(stream, options, policy(), lambda: None)
        assert inspected.count == 0 and len(inspected.read()) == 0
        assert summary["point_count"] == 0
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
