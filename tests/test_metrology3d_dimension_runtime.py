"""真实 Scope 与严格特征输入，独立解析模型验证测量不重复拟合。"""

import numpy as np
import pytest
import weakref

from backend.contracts.workflows.boundary3d import BoundarySelection, BoundaryTopology
from backend.contracts.workflows.boundary3d_observations import (
    CircleFeature,
    CircleMethod,
    LineFeature,
    LineMethod,
    BoundaryEvidence,
    BoundaryMethod,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.contracts.workflows.dimension3d_parameters import MeasureHoleParameters
from backend.contracts.workflows.point_cloud_runtime import BoundarySelectionMethod
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes._metrology3d_nodes.shared.geometry_quality import geometry_quality
from custom_nodes._metrology3d_nodes.shared.measure_edge_pair import measure_edge_pair
from custom_nodes._metrology3d_nodes.shared.measure_hole import measure_hole
from tests.test_metrology3d_boundary_contracts import (
    circle_parameters,
    line_parameters,
    evaluation,
)
from tests.test_metrology3d_dimension_contracts import dimension_policy
from tests.test_metrology3d_edge_pair import pair_parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.integration.metrology3d.test_boundary_extraction import (
    extract_parameters,
    region,
)
from custom_nodes._metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent


def analytic_fit_method(runtime, support, parameters, *, circle=False):
    """为独立解析特征记录同一实际支持，不调用被测拟合器生成真值。"""
    with runtime.borrow(support) as view:
        points = np.concatenate(
            [view.chunk(i, i + 1)["positions"] for i in range(support.point_count)]
        ).astype(float)
    checks, length = [], 0.0
    p = extract_parameters(
        feature_id=parameters.selection.feature_id,
        evaluation=parameters.evaluation,
        targets=[
            dict(segment_id=s.segment_id, region=region(), closed=s.closed, role=s.role)
            for s in support.topology.segments
        ],
    )
    for part in support.topology.segments:
        local = points[part.start : part.start + part.count]
        distance = float(np.linalg.norm(np.diff(local, axis=0), axis=1).sum())
        if part.closed:
            distance += float(np.linalg.norm(local[-1] - local[0]))
        length += distance
        quality = geometry_quality(
            support.observation_id,
            {
                "input_count": (support.point_count, "1"),
                "surface_point_count": (support.point_count, "1"),
                "face_count": (0, "1"),
                "candidate_count": (len(support.topology.segments), "1"),
                "support_count": (part.count, "1"),
                "length": (distance, "mm"),
            },
            p.quality_policy,
            reason="missing",
        )
        checks.append(dict(segment_id=part.segment_id, quality=quality))
    quality = geometry_quality(
        support.observation_id,
        {
            "input_count": (support.point_count, "1"),
            "surface_point_count": (support.point_count, "1"),
            "face_count": (0, "1"),
            "candidate_count": (len(checks), "1"),
            "support_count": (support.point_count, "1"),
            "length": (length, "mm"),
        },
        p.quality_policy,
        reason="missing",
    )
    boundary = BoundaryEvidence(
        feature_id=p.feature_id,
        valid=True,
        reason=None,
        failed_segment_id=None,
        geometry=support.topology,
        quality=quality,
        segments=checks,
        method=BoundaryMethod(
            parameters=p,
            parameters_sha256=parameter_digest(p),
            resolution=dict(
                observation_id=support.observation_id,
                evaluation=p.evaluation,
                height=None,
                pose=None,
                datum=None,
                measurement=None,
                reason=None,
            ),
        ),
    )
    return (CircleMethod if circle else LineMethod)(
        parameters=parameters,
        parameters_sha256=parameter_digest(parameters),
        evaluation=parameters.evaluation,
        boundary=boundary,
        boundary_content_sha256=freeze_cloud_parent(runtime, support)["content_sha256"],
    )


def ordered(runtime, root, rows, segments):
    """测试数据用现有只读有序视图，不另建资源或伪造引用。"""
    selection = BoundarySelection(
        feature_id="boundary", segment_ids=[s["segment_id"] for s in segments]
    )
    owner = own_output(
        runtime, {"indices": np.asarray(rows, dtype="<u4").reshape(-1, 1)}, []
    )
    return runtime.register_ordered(
        parent=root,
        indices=owner,
        topology=BoundaryTopology(point_count=len(rows), segments=segments),
        method=BoundarySelectionMethod(
            method_id="select-boundary",
            method_version=1,
            parameters=selection,
            parameters_sha256=parameter_digest(selection),
        ),
        cancel=lambda: None,
    )


def group(runtime, root, features):
    """同一观测的严格特征集合。"""
    return Features3d(
        run_id=runtime.run_id,
        observation_id=root.observation_id,
        frame_id="fixture",
        length_unit="mm",
        items=features,
    )


def analytic_edges(runtime, root):
    """x=0 和 x=4 的独立解析模型，实际支持 y=-2..2。"""
    features = []
    for i, x in enumerate((0, 4)):
        p = line_parameters(feature_id=("a", "b")[i], positive_direction=(0, 1, 0))
        support = ordered(
            runtime,
            root,
            [2 * i, 2 * i + 1],
            [
                dict(
                    segment_id="side",
                    start=0,
                    count=2,
                    closed=False,
                    role="open",
                    orientation="open",
                )
            ],
        )
        values = {
            "support_count": (2, "1"),
            "plane_max_residual": (0, "mm"),
            "span": (4, "mm"),
            "direction_gap": (1, "1"),
            "rms": (0, "mm"),
            "max_residual": (0, "mm"),
            "max_gap": (0, "mm"),
        }
        quality = geometry_quality(
            root.observation_id, values, p.quality_policy, reason="missing"
        )
        features.append(
            LineFeature(
                feature_id=p.feature_id,
                valid=True,
                reason=None,
                geometry=dict(origin=(x, 0, 0), direction=(0, 1, 0)),
                support=support,
                quality=quality,
                method=analytic_fit_method(runtime, support, p),
                intervals=[dict(segment_id="side", start=-2, end=2)],
            )
        )
    return group(runtime, root, features)


def hole_parameters(**changes):
    """测试启用全部圆心量，零坐标不得丢失。"""
    return MeasureHoleParameters(
        **{
            "evaluation": evaluation(),
            "feature_id": "circle",
            "target_kind": "closed-hole",
            "display_direction": (1, 0, 0),
            "quality_policy": dimension_policy(),
            "outputs": [
                dict(component=c, item_id=c)
                for c in ("diameter", "center_x", "center_y", "center_z")
            ],
            **changes,
        }
    )


def analytic_circle(runtime, root, *, closed=True, role="inner"):
    """独立给定圆模型及解析残差，验证尺寸入口不调用求解器。"""
    p = circle_parameters()
    count = root.point_count
    support = ordered(
        runtime,
        root,
        range(count),
        [
            dict(
                segment_id="arc",
                start=0,
                count=count,
                closed=closed,
                role=role,
                orientation="cw" if closed else "open",
            )
        ],
    )
    values = {
        "support_count": (count, "1"),
        "plane_max_residual": (0, "mm"),
        "rms": (0, "mm"),
        "max_residual": (0, "mm"),
        "angular_coverage": (2 * np.pi if closed else np.pi, "rad"),
        "max_gap": (0 if closed else np.pi, "rad"),
        "jacobian_ratio": (0.5, "1"),
    }
    quality = geometry_quality(
        root.observation_id, values, p.quality_policy, reason="missing"
    )
    feature = CircleFeature(
        feature_id="circle",
        valid=True,
        reason=None,
        geometry=dict(center=(0, 0, 0), normal=(0, 0, 1), radius=4),
        support=support,
        method=analytic_fit_method(runtime, support, p, circle=True),
        quality=quality,
        intervals=[
            dict(segment_id="arc", start_angle=0, sweep=2 * np.pi if closed else np.pi)
        ],
        solver=dict(status=1, nfev=1, cost=0, optimality=0, radius_at_bound=False),
    )
    return group(runtime, root, [feature])


def test_pair_real_runtime_swapping_signed_absolute_and_missing():
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[0, -2, 0], [0, 2, 0], [4, -2, 0], [4, 2, 0]], dtype=float
        ),
    )
    try:
        features = analytic_edges(runtime, root)
        for direction, mode, expected in (
            ((1, 0, 0), "signed", 4),
            ((-1, 0, 0), "signed", -4),
            ((-1, 0, 0), "absolute", 4),
        ):
            p = pair_parameters().model_copy(
                update={"direction": direction, "value_mode": mode}
            )
            result = measure_edge_pair(runtime, [features], p, cancel=lambda: None)
            assert result.items[0].value == expected
            assert (
                MeasurementEvidence3d.model_validate_json(result.model_dump_json())
                == result
            )
        p = pair_parameters().model_copy(update={"query_position": (0, 3, 0)})
        result = measure_edge_pair(runtime, [features], p, cancel=lambda: None)
        assert (
            result.items[0].value is None
            and result.items[0].reason == "outside_support"
        )
        with pytest.raises(InvalidRequestError, match="不存在"):
            measure_edge_pair(
                runtime,
                [features],
                p.model_copy(update={"target_feature_id": "missing"}),
                cancel=lambda: None,
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_support_scan_cancellation_does_not_pin_array_in_traceback(monkeypatch):
    """调用方保留异常时，已退出的扫描帧也不能持有数组块。"""
    import custom_nodes._metrology3d_nodes.shared.dimension_runtime as module

    scope, runtime, root = make_cloud(unit="mm", coordinates=np.ones((4, 3)))
    refs = []
    original = module._positions

    def positions(*args):
        block = original(*args)
        refs.append(weakref.ref(block))
        return block

    monkeypatch.setattr(module, "_rows", lambda *args: 1)
    monkeypatch.setattr(module, "_positions", positions)

    def cancel():
        if refs:
            raise InterruptedError("cancel after first block")

    try:
        with pytest.raises(InterruptedError) as failure:
            module.dimension_support(runtime, root, "source", cancel=cancel)
        assert failure.value.__traceback__ is not None
        assert refs and all(ref() is None for ref in refs)
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize(
    "closed,role,mode,valid",
    [
        (True, "inner", "closed-hole", True),
        (True, "outer", "closed-hole", False),
        (True, "unknown", "closed-hole", False),
        (False, "open", "open-arc", True),
        (False, "open", "closed-hole", False),
    ],
)
def test_hole_consumes_circle_without_refitting_and_preserves_zero(
    monkeypatch, closed, role, mode, valid
):
    angles = np.linspace(0, 2 * np.pi if closed else np.pi, 32, endpoint=not closed)
    points = np.column_stack((4 * np.cos(angles), 4 * np.sin(angles), np.zeros(32)))
    scope, runtime, root = make_cloud(unit="mm", coordinates=points)
    try:
        features = analytic_circle(runtime, root, closed=closed, role=role)

        def forbidden(*args, **kwargs):
            raise AssertionError("measurement must not fit again")

        monkeypatch.setattr(
            "custom_nodes._metrology3d_nodes.shared.boundary_fitting.least_squares",
            forbidden,
        )
        result = measure_hole(
            runtime, [features], hole_parameters(target_kind=mode), cancel=lambda: None
        )
        assert all(i.valid == valid for i in result.items)
        assert [i.value for i in result.items] == (
            [8, 0, 0, 0] if valid else [None] * 4
        )
        assert (
            MeasurementEvidence3d.model_validate_json(result.model_dump_json())
            == result
        )
        with pytest.raises(InvalidRequestError, match="类型"):
            measure_edge_pair(
                runtime,
                [features],
                pair_parameters().model_copy(update={"reference_feature_id": "circle"}),
                cancel=lambda: None,
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0
