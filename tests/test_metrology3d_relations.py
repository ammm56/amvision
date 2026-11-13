"""B13 独立解析真值；测试工程参数不作为生产默认。"""

from math import pi, sqrt

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.boundary3d_observations import (
    LineGeometry,
    LineInterval,
)
from backend.contracts.workflows.geometry3d import PlaneGeometry
from backend.contracts.workflows.relation3d_parameters import RelationParameters
from custom_nodes.metrology3d_nodes.shared.relation_geometry import relation_geometry
from tests.test_metrology3d_boundary_contracts import evaluation


def parameters(kind="point-point", *, projection=False, **options):
    """固定方法和两个角色；只在测试中提供明示条件数。"""
    point = dict(kind="coordinate", position=(0, 0, 0))
    line = dict(kind="line", feature_id="a")
    plane = dict(kind="plane", feature_id="a")
    relation = dict(kind=kind, reference=point, target=point)
    if kind == "point-line":
        relation.update(target=line, support_mode="finite")
    if kind == "point-plane":
        relation.update(
            target=plane, support_mode="model", value_mode="signed", coverage=None
        )
    if kind == "line-line":
        relation.update(
            reference=line,
            target=dict(kind="line", feature_id="b"),
            support_mode="model",
            min_crossing_sine=1e-4,
        )
    if kind.endswith("angle"):
        operand = line if kind == "line-angle" else plane
        relation.update(
            reference=operand,
            target=operand | {"feature_id": "b"},
            angle_mode="unoriented",
        )
    relation.update(options)
    return RelationParameters(
        space=dict(kind="projection", plane=evaluation(), min_direction_norm=1e-6)
        if projection
        else dict(kind="spatial", frame_id="fixture", length_unit="mm"),
        relation=relation,
        item_id="measurement",
        quality_policy=dict(
            policy_id="relations",
            policy_version=1,
            rules=[dict(item_id="geometry_usable", unit="1", lower=1)],
        ),
    )


def line(origin=(0, 0, 0), direction=(1, 0, 0)):
    """独立给定解析直线，不拟合输入。"""
    return LineGeometry(origin=origin, direction=direction)


def interval(start, end, name="segment"):
    """真实支持段，内部间隙不能由包围区间替代。"""
    return LineInterval(segment_id=name, start=start, end=end)


def calculate(p, a, b, **kwargs):
    """仅注入取消回调，预期不调用被测实现生成。"""
    return relation_geometry(p, a, b, cancel=lambda: None, **kwargs)


@pytest.mark.parametrize("projection,expected", [(False, 13), (True, 5)])
def test_point_distance_space_projection_and_translation(projection, expected):
    p = parameters(projection=projection)
    for offset in (np.zeros(3), np.array([1e8, -2e8, 3e8])):
        result = calculate(p, offset, offset + (3, 4, 12))
        assert result.reason is None and result.value == expected
    assert calculate(p, (1, 2, 3), (1, 2, 3)).value == 0


@pytest.mark.parametrize(
    "query,reason",
    [((1, 3, 4), None), ((3, 3, 4), "support_gap"), ((7, 3, 4), "outside_support")],
)
def test_point_line_does_not_clamp_or_bridge(query, reason):
    segments = (interval(0, 2), interval(4, 6, "second"))
    result = calculate(
        parameters("point-line"), query, line(), target_intervals=segments
    )
    assert result.reason == reason
    assert result.failed_role == ("target" if reason else None)
    assert result.value == (5 if reason is None else None)
    model = calculate(parameters("point-line", support_mode="model"), query, line())
    assert model.value == 5


def test_projected_line_maps_foot_back_to_original_support():
    direction = (1 / sqrt(2), 0, 1 / sqrt(2))
    p = parameters("point-line", projection=True)
    result = calculate(
        p, (2, 3, 9), line(direction=direction), target_intervals=(interval(0, 4),)
    )
    assert result.value == pytest.approx(3)
    assert result.target_point == pytest.approx((2, 0, 2))
    assert (
        calculate(
            p, (2, 3, 9), line(direction=(0, 0, 1)), target_intervals=(interval(0, 4),)
        ).reason
        == "projection_degenerate"
    )


def test_point_plane_sign_and_coverage_are_not_silently_skipped():
    target = PlaneGeometry(normal=(0, 0, 1), offset=-2)
    result = calculate(parameters("point-plane"), (1, 4, -1), target)
    assert result.value == -3 and result.target_point == (1, 4, 2)
    assert (
        calculate(
            parameters("point-plane", value_mode="absolute"), (1, 4, -1), target
        ).value
        == 3
    )
    finite = parameters(
        "point-plane",
        support_mode="finite",
        coverage=dict(
            support_radius=1,
            min_support_count=3,
            max_triangle_edge=1,
            max_plane_residual=0.01,
        ),
    )
    with pytest.raises(ValueError, match="coverage_required"):
        calculate(finite, (1, 4, -1), target)
    assert (
        calculate(
            finite, (1, 4, -1), target, plane_coverage=lambda point: "outside_support"
        ).value
        is None
    )
    assert (
        calculate(finite, (1, 4, -1), target, plane_coverage=lambda point: None).value
        == -3
    )


def test_skew_line_closest_pair_and_finite_support():
    a, b = line(), line((2, 0, 3), (0, 1, 0))
    p = parameters("line-line", support_mode="finite")
    result = calculate(
        p,
        a,
        b,
        reference_intervals=(interval(0, 4),),
        target_intervals=(interval(-1, 1),),
    )
    assert result.value == 3
    assert result.reference_point == pytest.approx((2, 0, 0))
    assert result.target_point == pytest.approx((2, 0, 3))
    missing = calculate(
        p,
        a,
        b,
        reference_intervals=(interval(0, 1),),
        target_intervals=(interval(-1, 1),),
    )
    assert missing.reason == "outside_support" and missing.value is None
    assert missing.failed_role == "reference"
    projected = calculate(parameters("line-line", projection=True), a, b)
    assert projected.value == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_parallel_lines_keep_nonunique_contacts_and_real_support(reverse):
    a = line()
    b = line((0, 3, 4), (-1, 0, 0) if reverse else (1, 0, 0))
    p = parameters("line-line", support_mode="finite")
    result = calculate(
        p,
        a,
        b,
        reference_intervals=(interval(0, 2),),
        target_intervals=(interval(-2, 0) if reverse else interval(0, 2),),
    )
    assert result.value == 5 and not result.contacts_unique
    assert result.reference_point is None and result.target_point is None
    assert result.support_pairs == (("segment", "segment"),)
    missing = calculate(
        p,
        a,
        b,
        reference_intervals=(interval(3, 4),),
        target_intervals=(interval(-2, 0) if reverse else interval(0, 2),),
    )
    assert missing.reason == "no_supported_closest_pair"


def test_near_parallel_is_not_treated_as_parallel():
    b = line((0, 1, 0), (np.cos(1e-5), np.sin(1e-5), 0))
    assert (
        calculate(parameters("line-line"), line(), b).reason
        == "ill_conditioned_closest_pair"
    )


def test_parallel_finite_contacts_can_be_unique_without_clamping():
    a, b = line(), line((0, 3, 4))
    p = parameters("line-line", support_mode="finite")
    result = calculate(
        p,
        a,
        b,
        reference_intervals=(interval(0, 2),),
        target_intervals=(interval(2, 4),),
    )
    assert result.value == 5 and result.contacts_unique
    assert result.reference_point == (2, 0, 0)
    assert result.target_point == (2, 3, 4)
    multiple = calculate(
        p,
        a,
        b,
        reference_intervals=(interval(0, 2), interval(4, 6, "second")),
        target_intervals=(interval(2, 4),),
    )
    assert multiple.value == 5 and not multiple.contacts_unique
    assert multiple.reference_point is None and multiple.target_point is None


@pytest.mark.parametrize(
    "mode,expected",
    [("unoriented", pi / 4), ("oriented", 3 * pi / 4), ("signed", 3 * pi / 4)],
)
def test_angle_modes_and_sign(mode, expected):
    p = parameters("line-angle", projection=True, angle_mode=mode)
    a, b = line(), line(direction=(-1 / sqrt(2), 1 / sqrt(2), 0))
    assert calculate(p, a, b).value == pytest.approx(expected)
    if mode == "signed":
        assert calculate(p, b, a).value == pytest.approx(-expected)
    assert calculate(p, a, line(direction=(0, 0, 1))).reason == "projection_degenerate"


def test_plane_angle_uses_normals_and_no_imaginary_signed_space_angle():
    a, b = (
        PlaneGeometry(normal=(0, 0, 1), offset=0),
        PlaneGeometry(normal=(0, 0, -1), offset=4),
    )
    assert calculate(parameters("plane-angle"), a, b).value == 0
    assert calculate(parameters("plane-angle", angle_mode="oriented"), a, b).value == pi
    with pytest.raises(ValidationError, match="显式评价面"):
        parameters("plane-angle", angle_mode="signed")
    with pytest.raises(ValidationError, match="空间模式"):
        parameters("point-plane", projection=True)


def test_contract_roundtrip_no_hidden_fields_or_quality_bypass():
    p = parameters()
    assert RelationParameters.model_validate_json(p.model_dump_json()) == p
    raw = p.model_dump(mode="json")
    raw["relation"]["support_mode"] = "model"
    with pytest.raises(ValidationError):
        RelationParameters.model_validate(raw)
    raw = p.model_dump(mode="json")
    raw["quality_policy"]["rules"][0]["lower"] = 0
    with pytest.raises(ValidationError, match="geometry_usable"):
        RelationParameters.model_validate(raw)


def test_angle_has_no_closest_contact_metric():
    p = parameters("line-angle")
    result = calculate(p, line(), line(direction=(0, 1, 0)))
    assert result.contacts_unique is None
    raw = p.model_dump(mode="json")
    raw["quality_policy"]["rules"].append(
        dict(item_id="contacts_unique", unit="1", lower=1)
    )
    with pytest.raises(ValidationError, match="未知指标"):
        RelationParameters.model_validate(raw)


def test_cancel_is_checked_before_calculation():
    def cancel():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        relation_geometry(parameters(), (0, 0, 0), (1, 0, 0), cancel=cancel)
