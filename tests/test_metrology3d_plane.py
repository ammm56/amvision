"""平面解析真值与退化测试；期望几何不调用被测拟合器生成。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.geometry3d import FitPlaneParameters
from backend.contracts.workflows.geometry3d_observations import PlaneFeature
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.fit_plane import fit_plane
from tests.point_cloud_support import policy
from tests.test_metrology3d_preprocess import make_cloud


def plane_parameters(**changes):
    """仅测试的质量门槛，不用于生产参数。"""
    values = dict(
        feature_id="plane",
        positive_normal=[0, 0, 1],
        min_orientation_cosine=0.1,
        algorithm=dict(kind="svd"),
        quality_policy=dict(
            policy_id="test",
            policy_version=1,
            rules=[
                dict(item_id="inlier_count", unit="1", lower=3),
                dict(item_id="tangent_ratio", unit="1", lower=0.01),
                dict(item_id="normal_gap", unit="1", lower=0.01),
                dict(item_id="rms", unit="mm", upper=0.001),
                dict(item_id="max_residual", unit="mm", upper=0.005),
            ],
        ),
    )
    return FitPlaneParameters(**{**values, **changes})


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("plane", ["horizontal", "vertical", "inclined"])
def test_plane_independent_truth(dtype, plane):
    xy = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1], [0, 0]], dtype=dtype)
    if plane == "horizontal":
        points = np.column_stack((xy, np.full(len(xy), 7)))
        normal, offset = [0, 0, 1], -7
    elif plane == "vertical":
        points = np.column_stack((np.full(len(xy), 2), xy))
        normal, offset = [1, 0, 0], -2
    else:
        points = np.column_stack((xy, 3 - xy[:, 0] - xy[:, 1]))
        normal, offset = np.ones(3) / np.sqrt(3), -np.sqrt(3)
    scope, runtime, cloud = make_cloud(unit="mm", coordinates=points.astype(dtype))
    result = fit_plane(
        runtime,
        cloud,
        plane_parameters(positive_normal=tuple(normal)),
        cancel=lambda: None,
    )
    feature = result.items[0]
    assert feature.valid
    np.testing.assert_allclose(feature.geometry.normal, normal, atol=1e-12)
    assert feature.geometry.offset == pytest.approx(offset, abs=1e-12)
    assert feature.quality.usable and feature.support == cloud
    flipped = fit_plane(
        runtime,
        cloud,
        plane_parameters(positive_normal=tuple(-np.asarray(normal))),
        cancel=lambda: None,
    )
    np.testing.assert_allclose(
        flipped.items[0].geometry.normal, -np.asarray(normal), atol=1e-12
    )
    assert not scope.close()
    assert runtime.budget.used == 0


@pytest.mark.parametrize(
    "points,reason",
    [
        ([[0, 0, 0], [1, 1, 1]], "insufficient_support"),
        ([[0, 0, 0], [1, 1, 1], [2, 2, 2]], "geometry_quality_failed"),
        ([[0, 0, 0], [0, 0, 0], [0, 0, 0]], "geometry_quality_failed"),
    ],
)
def test_unmeasurable_is_not_product_ng(points, reason):
    scope, runtime, cloud = make_cloud(
        unit="mm", coordinates=np.array(points, dtype=np.float64)
    )
    feature = fit_plane(runtime, cloud, plane_parameters(), cancel=lambda: None).items[
        0
    ]
    assert not feature.valid and feature.geometry is None
    assert feature.reason in {reason, "normal_direction_ambiguous"}
    assert not feature.quality.usable
    assert not scope.close()


def test_orientation_and_units_are_not_guessed():
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0, 0, 2], [1, 0, 2], [0, 1, 2]], dtype=np.float64),
    )
    feature = fit_plane(
        runtime, cloud, plane_parameters(positive_normal=(1, 0, 0)), cancel=lambda: None
    ).items[0]
    assert feature.reason == "normal_direction_ambiguous" and feature.geometry is None
    with pytest.raises(InvalidRequestError, match="未知指标"):
        fit_plane(
            runtime,
            cloud,
            plane_parameters(
                quality_policy=dict(
                    policy_id="bad",
                    policy_version=1,
                    rules=[
                        {**r.model_dump(), "unit": "m"}
                        for r in plane_parameters().quality_policy.rules
                    ],
                )
            ),
            cancel=lambda: None,
        )
    assert not scope.close()


def test_large_offset_and_unavailable():
    points = np.array(
        [[1e9, 1e9, 3], [1e9 + 1, 1e9, 3], [1e9, 1e9 + 1, 3], [1e9 + 1, 1e9 + 1, 3]]
    )
    scope, runtime, cloud = make_cloud(unit="mm", coordinates=points)
    feature = fit_plane(runtime, cloud, plane_parameters(), cancel=lambda: None).items[
        0
    ]
    assert feature.valid and feature.geometry.offset == pytest.approx(-3)
    unavailable = cloud.model_copy(
        update=dict(
            state="unavailable",
            reason="datum_missing",
            cloud_id=None,
            revision=None,
            point_count=None,
            fields=None,
            sample_origin=None,
        )
    )
    feature = fit_plane(
        runtime, unavailable, plane_parameters(), cancel=lambda: None
    ).items[0]
    assert feature.reason == "datum_missing" and feature.geometry is None
    assert not scope.close()


def test_plane_cancellation_and_invalid_positions_release_borrows():
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[0, 0, 3], [1, 0, 3], [0, 1, 3], [1, 1, 3]], dtype=np.float64
        ),
    )
    before = runtime.budget.used
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        fit_plane(runtime, cloud, plane_parameters(), cancel=cancel)
    assert runtime.budget.used == before
    assert not scope.close()
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0, 0, 3], [1, 0, 3], [0, 1, np.nan]], dtype=np.float64),
    )
    with pytest.raises(InvalidRequestError, match="无效位置"):
        fit_plane(runtime, cloud, plane_parameters(), cancel=lambda: None)
    assert not scope.close()


def test_ransac_capacity_rejected_before_library_import():
    scope, runtime, cloud = make_cloud(
        unit="mm", coordinates=np.ones((4, 3), dtype=np.float64)
    )
    p = plane_parameters(
        algorithm=dict(
            kind="ransac-svd",
            distance_threshold=0.01,
            sample_size=3,
            iterations=100,
            probability=0.999,
        )
    )
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError, match="工作预算"):
        fit_plane(runtime, cloud, p, cancel=lambda: None)
    assert runtime.budget.used == before
    assert not scope.close()


def test_ransac_capacity_includes_concurrent_candidate_indices():
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.ones((1000, 3), dtype=np.float32),
        runtime_policy=policy(max_working_bytes=262144, max_live_array_bytes=131072),
    )
    p = plane_parameters(
        algorithm=dict(
            kind="ransac-svd",
            distance_threshold=0.01,
            sample_size=3,
            iterations=100,
            probability=0.999,
        )
    )
    # 原来的单份点/索引估算小于 256 KiB，但所有候选内点集合可同时存在。
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError, match="工作预算"):
        fit_plane(runtime, cloud, p, cancel=lambda: None)
    assert runtime.budget.used == before
    assert not scope.close()


def test_quality_thresholds_must_be_explicit_and_supported():
    raw = plane_parameters().model_dump(mode="json")
    raw["quality_policy"]["rules"] = raw["quality_policy"]["rules"][:-1]
    with pytest.raises(ValidationError, match="max_residual"):
        FitPlaneParameters.model_validate(raw)
    raw = plane_parameters().model_dump(mode="json")
    raw["algorithm"] = {"kind": "ransac-svd"}
    with pytest.raises(ValidationError):
        FitPlaneParameters.model_validate(raw)


def test_residuals_use_all_support_and_reject_failed_quality():
    points = np.array(
        [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-0.002, 0.002)]
    )
    scope, runtime, cloud = make_cloud(unit="mm", coordinates=points)
    feature = fit_plane(runtime, cloud, plane_parameters(), cancel=lambda: None).items[
        0
    ]
    assert feature.reason == "geometry_quality_failed" and feature.geometry is None
    metrics = {m.item_id: m for m in feature.quality.metrics.items}
    assert metrics["rms"].value == pytest.approx(0.002, abs=1e-14)
    assert metrics["max_residual"].value == pytest.approx(0.002, abs=1e-14)
    assert not scope.close()


def test_quality_evidence_cannot_disagree_with_metrics_or_recipe():
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0, 0, 3], [1, 0, 3], [0, 1, 3]], dtype=np.float64),
    )
    feature = fit_plane(runtime, cloud, plane_parameters(), cancel=lambda: None).items[
        0
    ]
    raw = feature.model_dump(mode="json")
    raw["quality"]["checks"][0]["value"] = 10
    with pytest.raises(ValidationError, match="指标正文"):
        PlaneFeature.model_validate(raw)
    raw = feature.model_dump(mode="json")
    raw["quality"]["checks"][0]["lower"] = 2
    with pytest.raises(ValidationError, match="策略"):
        PlaneFeature.model_validate(raw)
    assert not scope.close()
