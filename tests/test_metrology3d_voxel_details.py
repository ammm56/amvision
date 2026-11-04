"""当前格映射及持久细节叶块，用原始成员独立核对。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.cloud_voxel import CloudVoxelGrid
from backend.contracts.workflows.geometry3d import require_rotation
from backend.contracts.workflows.point_cloud_runtime import NormalizeCloudUnits
from backend.service.application.workflows.point_cloud.detail_index import (
    prepare_index,
    read_block,
)
from custom_nodes.metrology3d_nodes.shared.normalize_units import normalize_units
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
from tests.test_metrology3d_resample import parameters
from tests.test_point_cloud_details import detail_policy
from tests.test_metrology3d_preprocess import make_cloud
from tests.point_cloud_support import create_resource_service


def test_grid_unit_conversion_and_complete_leaf_metadata(tmp_path):
    """原格以米声明；当前坐标和细节仍应正确显示毫米格。"""
    p = detail_policy()
    points = np.array(
        [[0, 0, 0], [0.001, 0, 0], [0.003, 0, 0], [0.003, 0.001, 0]], dtype="f8"
    )
    scope, runtime, source = make_cloud(
        unit="m", coordinates=points, runtime_policy=p.io
    )
    settings = parameters("voxel-centroid").settings.model_copy(
        update=dict(voxel_size=0.002, length_unit="m", frame_id=source.spatial.frame_id)
    )
    try:
        sampled, _ = resample_cloud(
            runtime,
            source,
            parameters("voxel-centroid").model_copy(update=dict(settings=settings)),
            cancel=lambda: None,
        )
        normalized = normalize_units(
            runtime, sampled, NormalizeCloudUnits(), cancel=lambda: None
        )
        assert normalized.voxel_aggregation.parameters.settings.length_unit == "m"
        np.testing.assert_array_equal(normalized.voxel_grid.axes, np.eye(3) * 2)
        service = create_resource_service(tmp_path)
        asset = save_cloud(
            runtime,
            normalized,
            service=service,
            project_id="test",
            name="voxel",
            mode="derived",
            write_identity="f" * 64,
            policy=p.assets(),
            cancel=lambda: None,
        )
        restored = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=p.assets(),
            cancel=lambda: None,
        )
        index = prepare_index(
            runtime,
            restored,
            service=service,
            project_id="test",
            policy=p,
            cancel=lambda: None,
        )
        assert index.voxel.grid == normalized.voxel_grid
        assert index.voxel.aggregation == sampled.voxel_aggregation
        seen = []
        for block in index.blocks:
            raw = read_block(
                service,
                index.source,
                block.block_id,
                generation=index.generation,
                project_id="test",
                policy=p.preview,
            )
            keys = np.ndarray(
                (block.count, 3),
                dtype="<i8",
                buffer=raw,
                offset=index.voxel.keys_offset,
                strides=(index.row_bytes, 8),
            )
            counts = np.ndarray(
                (block.count,),
                dtype="<u8",
                buffer=raw,
                offset=index.voxel.members_offset,
                strides=(index.row_bytes,),
            )
            seen.extend((tuple(k), int(c)) for k, c in zip(keys, counts))
        assert sorted(seen) == [((0, 0, 0), 2), ((1, 0, 0), 2)]
    finally:
        assert not scope.close()
    assert runtime.budget.used == 0


@pytest.mark.parametrize(
    "axes",
    [
        np.zeros((3, 3)),
        np.diag([1, 2, 1]),
        np.diag([-1, 1, 1]),
        [[1, 0, 0], [1, 1, 0], [0, 0, 1]],
    ],
)
def test_grid_rejects_invalid_geometry(axes):
    """错误格不能作为看似合法的拾取盒显示。"""
    with pytest.raises(ValidationError):
        CloudVoxelGrid(origin=[0, 0, 0], axes=np.asarray(axes).tolist())


def test_grid_accepts_platform_rotation_precision():
    """已通过公开刚体输入校验的舍入误差不能被显示格框再次拒绝。"""
    rotation = np.array([[1, 4e-9, 0], [0, 1, 0], [0, 0, 1]])
    require_rotation(rotation.tolist())
    grid = CloudVoxelGrid(origin=[0, 0, 0], axes=(rotation.T * 2).tolist())
    np.testing.assert_array_equal(grid.axes, rotation.T * 2)
