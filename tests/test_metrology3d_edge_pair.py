"""边对解析公式的独立真值；实际 Runtime 和拟合组合另行验证。"""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.contracts.workflows.boundary3d_observations import (
    LineGeometry,
    LineInterval,
)
from backend.contracts.workflows.dimension3d_parameters import MeasureEdgePairParameters
from custom_nodes.metrology3d_nodes.shared.measure_edge_pair import _intersection
from tests.test_metrology3d_boundary_contracts import evaluation
from tests.test_metrology3d_dimension_contracts import dimension_policy


def pair_parameters(**changes):
    """测试平面和求交条件均显式给定。"""
    return MeasureEdgePairParameters(
        **{
            **dict(
                evaluation=evaluation(),
                outputs=[dict(component="distance", item_id="gap")],
                quality_policy=dimension_policy(),
                reference_feature_id="a",
                target_feature_id="b",
                query_position=(0, 0, 0),
                direction=(1, 0, 0),
                value_mode="signed",
                max_plane_distance=1e-8,
                max_plane_angle_radians=1e-8,
                min_crossing_sine=0.01,
            ),
            **changes,
        }
    )


def line(origin=(4, 0, 0), direction=(0, 1, 0), intervals=((-2, 2),), plane=None):
    """独立解析直线，不运行 TLS 构造期望。"""
    return SimpleNamespace(
        geometry=LineGeometry(origin=origin, direction=direction),
        intervals=[
            LineInterval(segment_id=f"segment-{i}", start=a, end=b)
            for i, (a, b) in enumerate(intervals)
        ],
        method=SimpleNamespace(evaluation=plane or evaluation()),
    )


@pytest.mark.parametrize("y", [-2, 0, 2])
@pytest.mark.parametrize("direction", [(1, 0, 0), (-1, 0, 0)])
def test_analytic_intersection_endpoints_and_direction(y, direction):
    p = pair_parameters().model_copy(
        update={"query_position": (0, y, 0), "direction": direction}
    )
    reason, metrics, hit = _intersection(line(), p)
    assert reason is None and metrics["supported"] == 1
    assert hit[0] == 4 * direction[0] and hit[1] == y
    assert hit[2] == (4, y, 0)


@pytest.mark.parametrize(
    "y,reason", [(-3, "outside_support"), (0, "support_gap"), (3, "outside_support")]
)
def test_union_never_fills_gap_or_extrapolates(y, reason):
    p = pair_parameters().model_copy(update={"query_position": (0, y, 0)})
    actual, metrics, hit = _intersection(line(intervals=((-2, -1), (1, 2))), p)
    assert actual == reason and metrics["supported"] == 0 and hit is None


def test_wedge_intersection_changes_with_query_position():
    model = line(
        origin=(4, 0, 0),
        direction=(1 / np.sqrt(2), 1 / np.sqrt(2), 0),
        intervals=((-10, 10),),
    )
    for y in (-1, 0, 1):
        p = pair_parameters().model_copy(update={"query_position": (0, y, 0)})
        reason, _, hit = _intersection(model, p)
        assert reason is None and hit[0] == pytest.approx(4 + y)


def test_parallel_and_out_of_plane_are_not_projected_into_success():
    reason, _, _ = _intersection(line(direction=(1, 0, 0)), pair_parameters())
    assert reason == "ill_conditioned_intersection"
    reason, _, _ = _intersection(line(origin=(4, 0, 0.1)), pair_parameters())
    assert reason == "non_coplanar"
    plane = evaluation(rotation=((1, 0, 0), (0, 0, -1), (0, 1, 0)))
    reason, _, _ = _intersection(line(plane=plane), pair_parameters())
    assert reason == "non_coplanar"
