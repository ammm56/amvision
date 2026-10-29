"""动态边界释放原运行后保存恢复，继承旧截面而不是复用旧运行权限。"""

from dataclasses import replace
import numpy as np
import pytest

from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.boundary_assets import restore_boundary
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary
from custom_nodes.metrology3d_nodes.shared.measure_extents import measure_extents
from tests.point_cloud_support import create_resource_service
from tests.test_point_cloud_assets import POLICY
from tests.test_metrology3d_dynamic_contour import fixture, extract, inherited
from tests.test_metrology3d_boundary_contracts import line_parameters
from tests.test_metrology3d_dimension_contracts import extent_parameters


def contents(runtime, cloud):
    """读取测试支持也遵守当前块大小，不扩大运行预算。"""
    points, edges = [], []
    with runtime.borrow(cloud) as view:
        for start in range(0, cloud.point_count, runtime.policy.chunk_rows):
            stop = min(start + runtime.policy.chunk_rows, cloud.point_count)
            points.append(view.chunk(start, stop)["positions"].copy())
            edges.append(view.lineage_chunk(start, stop)["source_edges"].copy())
    return np.concatenate(points), np.concatenate(edges)


def test_dynamic_boundary_saved_restored_and_fitted(tmp_path):
    values, parameters, measured = fixture()
    scope, runtime, *_ = values
    service = create_resource_service(tmp_path)
    limits = runtime.policy
    assets = replace(
        POLICY,
        max_asset_bytes=1024 * 1024,
        max_archive_bytes=2 * 1024 * 1024,
        chunk_bytes=128,
    )
    try:
        group = extract(values, parameters, measured)
        feature = group.items[0]
        assert feature.valid
        original, edges = contents(runtime, feature.support)
        asset = save_cloud(
            runtime,
            feature.support,
            features=group,
            service=service,
            project_id="test",
            mode="derived",
            name="dynamic-boundary",
            write_identity="c" * 64,
            policy=assets,
            cancel=lambda: None,
        )
        content = service.read(asset, project_id="test").content.point_cloud
        source_observation = feature.method.resolution.observation_id
    finally:
        assert not scope.close() and runtime.budget.used == 0
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="restored-dynamic", policy=limits)
    try:
        cloud = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=assets,
            cancel=lambda: None,
        )
        restored = restore_boundary(cloud, content.boundary)
        feature = restored.items[0]
        assert feature.method.resolution.observation_id == source_observation
        assert restored.observation_id != source_observation
        restored_points, restored_edges = contents(runtime, cloud)
        np.testing.assert_array_equal(restored_points, original)
        np.testing.assert_array_equal(restored_edges, edges)
        fitted = fit_boundary(
            runtime,
            restored,
            line_parameters(
                selection=dict(feature_id="boundary", segment_ids=["left"]),
                evaluation=inherited(),
                positive_direction=dict(kind="axis", axis="v"),
            ),
            cancel=lambda: None,
        )
        assert fitted.items[0].valid
        result = measure_extents(
            runtime,
            extent_parameters(
                evaluation=inherited(),
                source=dict(
                    kind="boundary",
                    selection=dict(
                        feature_id="boundary", segment_ids=["left", "right"]
                    ),
                ),
            ),
            groups=[restored],
            cancel=lambda: None,
        )
        assert [i.value for i in result.items] == pytest.approx([10, 4], abs=1e-10)
    finally:
        assert not scope.close() and runtime.budget.used == 0
