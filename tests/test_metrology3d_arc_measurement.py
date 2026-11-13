"""B10 独立解析圆、真实 Scope 和严格证据；不以拟圆输出生成真值。"""

from copy import deepcopy
from math import pi

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.boundary3d import BoundarySelection, BoundaryTopology
from backend.contracts.workflows.boundary3d_observations import CircleGeometry
from backend.contracts.workflows.dimension3d_parameters import MeasureArcParameters
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from custom_nodes.metrology3d_nodes.shared.arc_measurement import analyze_arc
from custom_nodes.metrology3d_nodes.shared.measure_arc import measure_arc
from tests.test_metrology3d_boundary_contracts import evaluation, topology
from tests.test_metrology3d_dimension_contracts import dimension_policy
from tests.test_metrology3d_dimension_runtime import analytic_circle
from tests.test_metrology3d_preprocess import make_cloud
from tests.point_cloud_support import policy


def arc_parameters(*, union=False, reverse=False, **changes):
    """显式测试参数不作为生产默认值。"""
    components = (
        ("coverage_angle", "supported_length")
        if union
        else ("signed_sweep", "arc_length", "chord_length")
    )
    return MeasureArcParameters.model_validate(
        dict(
            evaluation=dict(kind="feature", frame_id="fixture", length_unit="mm"),
            selection=dict(feature_id="circle", segment_ids=["arc"]),
            mode=dict(kind="supported-union")
            if union
            else dict(
                kind="continuous-arc",
                traversal="reverse-source-order" if reverse else "source-order",
            ),
            outputs=[dict(component=c, item_id=c) for c in components],
            quality_policy=dimension_policy(),
        )
        | changes
    )


def points(angles, radius=4):
    """圆的解析采样，真实折线比模型弧短。"""
    return np.column_stack(
        (radius * np.cos(angles), radius * np.sin(angles), np.zeros(len(angles)))
    )


def kernel(
    angles,
    *,
    union=False,
    reverse=False,
    closed=False,
    parts=None,
    maximum_step=0.5,
    cancel=lambda: None,
):
    """无运行平台依赖的角度内核验证入口。"""
    p = arc_parameters(union=union, reverse=reverse)
    t = topology(len(angles), closed=closed) if parts is None else parts
    selection = BoundarySelection(
        feature_id="circle", segment_ids=[s.segment_id for s in t.segments]
    )
    return analyze_arc(
        points(angles),
        t,
        CircleGeometry(center=(0, 0, 0), normal=(0, 0, 1), radius=4),
        evaluation(),
        selection,
        p.mode,
        maximum_step=maximum_step,
        max_working_bytes=10**7,
        cancel=cancel,
    )


@pytest.mark.parametrize("start,sweep", [(0, pi), (6, 1.2), (0, -pi), (-2, -1.5)])
@pytest.mark.parametrize("reverse", [False, True])
def test_open_arc_signed_cross_zero_and_reverse(start, sweep, reverse):
    result = kernel(np.linspace(start, start + sweep, 40), reverse=reverse)
    assert result.reason is None
    g = result.geometry
    assert g["signed_sweep"] == pytest.approx(sweep * (-1 if reverse else 1))
    assert g["coverage_angle"] == pytest.approx(abs(sweep))
    assert g["polyline_length"] < 4 * abs(sweep)
    assert g["start"]["vertex_index"] == (39 if reverse else 0)


@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_tilted_translated_arc_preserves_directed_measurement(dtype):
    """旋转和平移后的独立几何真值，容差仅覆盖输入表示误差。"""
    from scipy.spatial.transform import Rotation

    rotation = Rotation.from_euler("xyz", [0.4, -0.3, 0.7]).as_matrix()
    center = np.array([1000.0, -2000.0, 3000.0])
    data = (points(np.linspace(5.9, 7.4, 70)) @ rotation.T + center).astype(dtype)
    result = analyze_arc(
        data,
        topology(70, closed=False),
        CircleGeometry(center=center, radius=4, normal=rotation[:, 2]),
        evaluation(origin=center, rotation=rotation),
        arc_parameters().selection,
        arc_parameters().mode,
        maximum_step=0.5,
        max_working_bytes=10**7,
        cancel=lambda: None,
    )
    assert result.reason is None
    assert result.geometry["signed_sweep"] == pytest.approx(
        1.5, abs=1e-4 if dtype == "float32" else 1e-12
    )
    np.testing.assert_allclose(
        result.geometry["start"]["point"], data[0], rtol=0, atol=0
    )


def test_kernel_explicit_budget_and_unknown_selection_fail():
    data = points(np.linspace(0, 1, 10))
    p = arc_parameters()
    with pytest.raises(ValueError, match="budget"):
        analyze_arc(
            data,
            topology(10, closed=False),
            CircleGeometry(center=(0, 0, 0), radius=4, normal=(0, 0, 1)),
            evaluation(),
            p.selection,
            p.mode,
            maximum_step=0.5,
            max_working_bytes=10,
            cancel=lambda: None,
        )


def test_union_overlap_deduplicates_and_does_not_bridge_gap():
    angles = np.r_[
        np.linspace(0, 1.5, 20), np.linspace(1, 2, 20), np.linspace(3, 3.5, 20)
    ]
    t = BoundaryTopology(
        point_count=60,
        segments=[
            dict(
                segment_id=f"part-{i}",
                start=i * 20,
                count=20,
                closed=False,
                role="open",
                orientation="open",
            )
            for i in range(3)
        ],
    )
    result = kernel(angles, union=True, parts=t)
    assert result.reason is None
    g = result.geometry
    assert g["coverage_angle"] == pytest.approx(2.5)
    assert g["overlap_angle"] == pytest.approx(0.5)
    assert len(g["pieces"]) == 2
    assert g["start"] is g["end"] is g["direction"] is g["signed_sweep"] is None


def test_backtracking_only_union_is_valid_and_preserves_diagnosis():
    angles = np.r_[np.linspace(0, 1, 20), np.linspace(0.9, 0.2, 20)]
    assert kernel(angles).reason == "nonmonotonic_arc"
    result = kernel(angles, union=True)
    assert result.reason is None
    assert result.geometry["parts"][0]["angular_reason"] == "nonmonotonic_arc"
    assert result.geometry["coverage_angle"] == pytest.approx(1)


def test_closed_topology_has_no_global_endpoints():
    angles = np.linspace(0, 2 * pi, 64, endpoint=False)
    assert kernel(angles, closed=True).reason == "requires_single_open_segment"
    result = kernel(angles, closed=True, union=True)
    assert result.reason is None
    assert result.geometry["coverage_angle"] == pytest.approx(2 * pi)
    assert result.geometry["start"] is None
    assert result.geometry["parts"][0]["closed"]


def test_open_revolution_gap_duplicate_and_cancellation_rejected():
    assert kernel(np.linspace(0, 2 * pi, 80)).reason == "requires_open_sweep"
    assert kernel(np.array([0, 0.1, 1.0, 1.1])).reason == "angular_support_gap"
    assert kernel(np.array([0, 0.1, 0.1, 0.2])).reason == "degenerate_arc_edge"

    def cancel():
        raise InterruptedError("cancel")

    with pytest.raises(InterruptedError):
        kernel(np.linspace(0, 1, 20), cancel=cancel)


@pytest.mark.parametrize("union", [False, True])
def test_scope_output_units_roundtrip_and_no_refit(union, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("B10 must not refit")

    monkeypatch.setattr("scipy.optimize.least_squares", forbidden)
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=points(np.linspace(0, pi, 65)),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    try:
        features = analytic_circle(runtime, root, closed=False, role="open")
        result = measure_arc(
            runtime, [features], arc_parameters(union=union), cancel=lambda: None
        )
        assert all(i.valid for i in result.items)
        assert [i.value for i in result.items][:2] == pytest.approx([pi, 4 * pi])
        assert [i.unit for i in result.numeric_table().items][:2] == ["rad", "mm"]
        assert (
            MeasurementEvidence3d.model_validate_json(result.model_dump_json())
            == result
        )
        assert "cloud_id" not in result.model_dump_json()
        g = result.items[0].geometry
        if not union:
            assert g.start.source_index == 0 and g.end.source_index == 64
            assert g.start.lineage is None
        for change in ("value", "coverage", "source", "quality"):
            body = deepcopy(result.model_dump(mode="json"))
            for item in body["items"]:
                if change == "value":
                    item["value"] += 1
                if change == "coverage":
                    item["geometry"]["coverage_angle"] += 0.1
                if change == "source":
                    item["geometry"]["circle"]["radius"] += 1
                if change == "quality":
                    item["support"][0]["feature"]["quality"]["metrics"]["items"][0][
                        "value"
                    ] += 1
            with pytest.raises(ValidationError):
                MeasurementEvidence3d.model_validate(body)
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_generated_endpoints_preserve_edge_sources_and_scope():
    """生成边只有插值来源，不能为圆上构造点分配原始行号。"""
    from tests.test_point_cloud_lineage import boundary_method
    from tests.test_point_cloud_runtime import own

    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=points(np.linspace(0, pi, 6)),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    try:
        cloud = runtime.register_generated(
            parent=root,
            method=boundary_method(),
            owner=own(
                runtime, {"positions": points(np.array([0.0, 0.1, 0.2])).astype("<f8")}
            ),
            lineage=own(
                runtime,
                {
                    "source_edges": np.array([[1, 3], [2, 4], [3, 5]], dtype="<u8"),
                    "weights": np.array(
                        [[0.25, 0.75], [0.5, 0.5], [0.75, 0.25]], dtype="<f8"
                    ),
                    "face_offsets": np.array([[0], [1], [2], [3]], dtype="<u8"),
                    "source_faces": np.array(
                        [[1, 2, 3], [2, 3, 4], [3, 4, 5]], dtype="<u8"
                    ),
                },
            ),
            point_count=3,
            fields=root.fields,
            topology=dict(
                point_count=3,
                segments=[
                    dict(
                        segment_id="edge",
                        start=0,
                        count=3,
                        closed=False,
                        role="open",
                        orientation="open",
                    )
                ],
            ),
            cancel=lambda: None,
        )
        group = analytic_circle(runtime, cloud, closed=False, role="open")
        result = measure_arc(runtime, [group], arc_parameters(), cancel=lambda: None)
        g = result.items[0].geometry
        assert g.start.source_index is None and g.end.source_index is None
        assert g.start.lineage.source_edge == (1, 3)
        assert g.end.lineage.source_edge == (3, 5)
        assert g.start.lineage.weights == (0.25, 0.75)
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_mode_and_output_contract_reject_ambiguous_definitions():
    document = arc_parameters(union=True).model_dump(mode="json")
    document["outputs"] = [dict(component="start_x", item_id="x")]
    with pytest.raises(ValidationError):
        MeasureArcParameters.model_validate(document)
    document = arc_parameters().model_dump(mode="json")
    document["selection"]["segment_ids"] = ["a", "b"]
    with pytest.raises(ValidationError):
        MeasureArcParameters.model_validate(document)
