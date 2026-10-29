"""原生 RANSAC 后仍检查完整局部候选，不误把选中一层当唯一表面。"""

from custom_nodes.metrology3d_nodes.shared.height_query import height_query
from custom_nodes.metrology3d_nodes.shared.geometry_preview import attach_geometry
from custom_nodes.metrology3d_nodes.shared.preview import build_cloud_preview
from tests.test_metrology3d_height_step import two_planes
from tests.test_metrology3d_measurement_contracts import height_parameters
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preview import preview_policy


def test_native_ransac_does_not_hide_second_layer_and_displays_rejected_points():
    scope, runtime, cloud, _, _, groups = two_planes(mixed=True)
    configured = preview_policy(
        max_points=27, max_body_bytes=131072, max_working_bytes=1024 * 1024
    )
    try:
        p = height_parameters(
            plane_fit=plane_parameters(
                feature_id="target",
                algorithm=dict(
                    kind="ransac-svd",
                    distance_threshold=0.01,
                    sample_size=3,
                    iterations=100,
                    probability=0.999,
                ),
            )
        )
        result, local = height_query(runtime, cloud, groups[:1], p, cancel=lambda: None)
        assert local.items[0].valid
        assert not result.items[0].valid and result.items[0].value is None
        assert result.items[0].support[1].coverage.max_residual > 0.19
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=27, color=dict(mode="solid")),
            policy=configured,
            cancel=lambda: None,
        )
        display = attach_geometry(
            runtime,
            cloud,
            body,
            {"features": [local.model_dump(mode="json")]},
            policy=configured,
            cancel=lambda: None,
        )
        samples = display["geometry"]["planes"][0]["samples"]
        assert samples["classes"][:9] == [0] * 9
        assert samples["classes"].count(1) == 9 and samples["classes"].count(2) == 9
        rejected = [
            abs(value)
            for kind, value in zip(samples["classes"], samples["residuals"])
            if kind == 2
        ]
        assert min(rejected) > 0.19
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
