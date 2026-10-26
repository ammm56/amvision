"""M3.1 参数严格性；所有数值仅用于测试，不作为生产默认。"""

import pytest
from pydantic import ValidationError

from backend.contracts.workflows.measurement3d_parameters import (
    HeightQueryParameters,
    MeasureStepParameters,
    distance_metric_units,
    statistic_metric_units,
)
from backend.contracts.workflows.measurement3d_directional import (
    CoverageEvidence,
    ProjectionStatistics,
)
from tests.test_metrology3d_plane import plane_parameters


def measurement_policy(*, statistic=False, **overrides):
    """显式测试门槛，包括拒绝空洞的最大三角边长。"""
    units = (statistic_metric_units if statistic else distance_metric_units)("mm")
    rules = []
    for name, unit in units.items():
        bounds = (
            {"lower": 1 if statistic else 3}
            if name.endswith("_count")
            else {"lower": 1}
            if name.endswith("_covered")
            else {"lower": 0.1}
            if name.endswith("_cosine")
            else {"upper": 0.01}
            if name.endswith("_residual")
            else {"upper": 2}
        )
        rules.append(
            {"item_id": name, "unit": unit, **bounds, **overrides.get(name, {})}
        )
    return dict(policy_id="measurement-test", policy_version=1, rules=rules)


def height_parameters(**changes):
    """在测试坐标中搜索 Z=5 的局部面。"""
    return HeightQueryParameters(
        **{
            "item_id": "height",
            "frame_id": "fixture",
            "length_unit": "mm",
            "query": dict(
                kind="configured", query_position=(0, 0, 0), direction=(0, 0, 1)
            ),
            "support_radius": 2,
            "reference_policy": {"kind": "measured-support"},
            "quality_policy": measurement_policy(),
            "reference_feature_id": "reference",
            "search_radius": 2,
            "search_interval": (4, 6),
            "plane_fit": plane_parameters(feature_id="target"),
            **changes,
        }
    )


def step_parameters(*, statistic=None, **changes):
    """构造两种互斥测试测量，不共享隐藏模式参数。"""
    mode = (
        dict(
            kind="directional-planes",
            query=dict(
                kind="configured", query_position=(0, 0, 0), direction=(0, 0, 1)
            ),
            support_radius=2,
            reference_policy={"kind": "measured-support"},
            quality_policy=measurement_policy(),
            reference_feature_id="reference",
            target_feature_id="target",
        )
        if statistic is None
        else dict(
            kind="roi-statistic",
            origin=(0, 0, 0),
            direction=(0, 0, 1),
            statistic=statistic,
            quality_policy=measurement_policy(statistic=True),
        )
    )
    return MeasureStepParameters(
        item_id="step", frame_id="fixture", length_unit="mm", mode={**mode, **changes}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {
            "query": dict(
                kind="configured", query_position=(0, 0, 0), direction=(0, 0, 2)
            )
        },
        {"search_interval": (6, 4)},
        {"search_radius": 0},
        {"support_radius": 0},
        {"reference_feature_id": "target"},
        {"allow_extrapolation": True},
        {"quality_policy": measurement_policy(reference_covered={"lower": 0})},
        {"quality_policy": measurement_policy(reference_direction_cosine={"lower": 0})},
        {"quality_policy": measurement_policy(target_count={"required": False})},
    ],
)
def test_height_strict_parameters(changes):
    with pytest.raises(ValidationError):
        height_parameters(**changes)


def test_modes_are_disjoint_and_quantile_method_is_explicit():
    assert height_parameters().plane_fit.feature_id == "target"
    assert step_parameters().mode.kind == "directional-planes"
    assert step_parameters(statistic={"kind": "median"}).mode.kind == "roi-statistic"
    with pytest.raises(ValidationError):
        step_parameters(statistic={"kind": "quantile", "probability": 0.5})
    with pytest.raises(ValidationError):
        step_parameters(statistic={"kind": "mean"}, target_feature_id="old")


def test_coverage_and_statistics_cannot_claim_missing_support():
    with pytest.raises(ValidationError):
        CoverageEvidence(
            count=0,
            covered=True,
            nearest_distance=None,
            triangle_edge=None,
            max_residual=None,
            direction_cosine=1,
            triangle=None,
            source_indices=None,
        )
    with pytest.raises(ValidationError):
        ProjectionStatistics(count=2, value=4, mean=1, std=0, min=0, max=2)
