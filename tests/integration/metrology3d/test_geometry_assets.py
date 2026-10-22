"""M2 派生方法沿既有资源 v2 保存恢复，不另建几何资产系统。"""

from io import BytesIO

import numpy as np

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
from custom_nodes._metrology3d_nodes.shared.io.formats import inspect_cloud_file
from custom_nodes._metrology3d_nodes.shared.transform_cloud import transform_cloud
from tests.point_cloud_support import create_resource_service, policy
from tests.test_metrology3d_transform import transform_source, cloud_pose


def test_transformed_asset_preserves_values_and_method_identity(tmp_path):
    """关闭原运行后恢复新身份，历史矩阵仍是原方法快照而非运行权限。"""
    service = create_resource_service(tmp_path)
    scope, runtime, cloud = transform_source(np.float64)
    other = ResourceScope(kind="workflow")
    target = get_cloud_runtime(other, run_id="restored-run", policy=policy())
    limits = CloudAssetPolicy(
        max_asset_bytes=65536, max_archive_bytes=131072, chunk_bytes=128
    )
    try:
        _, pose = cloud_pose(runtime, cloud)
        result = transform_cloud(runtime, cloud, pose, cancel=lambda: None)
        expected_method = result.provenance.method
        saved = save_cloud(
            runtime,
            result,
            service=service,
            project_id="test",
            name="Transformed",
            mode="derived",
            write_identity="e" * 64,
            policy=limits,
            cancel=lambda: None,
        )
        document = service.read(saved, project_id="test")
        assert document.content.point_cloud.provenance.method == expected_method
        assert not scope.close() and runtime.budget.used == 0
        restored = read_asset(
            target,
            saved,
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        assert restored.run_id == "restored-run" and restored.spatial.frame_id == "part"
        with target.borrow(restored) as view:
            np.testing.assert_array_equal(
                view.chunk(0, 2)["positions"], [[0, 0, 0], [0, -1, 0]]
            )
            assert int(view.chunk(0, 2)["label"][0, 0]) == 2**64 - 1
            np.testing.assert_array_equal(view.source_indices(2, 4), [2, 3])
        stream = BytesIO()
        summary, options = export_cloud_file(
            target,
            restored,
            CloudExportOptions(
                profile_id="pcd-binary",
                profile_version=1,
                fields=["positions", "normals", "colors", "label"],
                file_name="transformed.pcd",
                spatial_acknowledged=True,
            ),
            stream=stream,
            max_output_bytes=65536,
            cancel=lambda: None,
        )
        assert summary["fields_omitted"] == []
        stream.seek(0)
        arrays = inspect_cloud_file(stream, options, policy(), lambda: None).read()
        np.testing.assert_array_equal(arrays["x"], [0, 0, 1, 1])
        np.testing.assert_array_equal(arrays["ny"], [-1, -1, -1, -1])
        assert int(arrays["label"][0]) == 2**64 - 1
    finally:
        assert not scope.close()
        assert not other.close() and target.budget.used == 0
