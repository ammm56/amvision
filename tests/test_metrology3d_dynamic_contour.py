"""本次等高、继承评价面和严格来源的独立几何真值。"""

from copy import deepcopy

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.boundary3d import ExtractBoundaryParameters
from backend.contracts.workflows.boundary3d_observations import BoundaryEvidence
from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes._metrology3d_nodes.shared.fit_boundary import fit_boundary
from custom_nodes._metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes._metrology3d_nodes.shared.measure_edge_pair import measure_edge_pair
from custom_nodes._metrology3d_nodes.shared.measure_extents import measure_extents
from custom_nodes._metrology3d_nodes.shared.measure_step import measure_step
from custom_nodes._metrology3d_nodes.shared.measure_hole import measure_hole
from tests.integration.metrology3d.test_boundary_extraction import extract_parameters
from tests.point_cloud_support import policy
from tests.test_metrology3d_boundary_contracts import line_parameters, evaluation
from tests.test_metrology3d_boundary_contracts import circle_parameters
from tests.test_metrology3d_dimension_contracts import extent_parameters
from tests.test_metrology3d_dimension_runtime import hole_parameters
from tests.test_metrology3d_edge_pair import pair_parameters
from tests.test_metrology3d_measurement_contracts import step_parameters
from tests.test_metrology3d_pose_query import tilted_fixture, query
from tests.test_metrology3d_plane import plane_parameters


def inherited():
    """测试输入空间固定，评价几何必须继承当前边界。"""
    return dict(kind="feature", frame_id="fixture", length_unit="mm")


def fixture(dtype=np.float64):
    """两个斜坡 z=x-10 / z=x-20，被 z=2.525 截出相距10的有限直边。"""
    extra = [
        (offset + x, y, x)
        for offset in (10, 20)
        for x in np.linspace(0, 4, 17)
        for y in np.linspace(-2, 2, 17)
    ]
    values = tilted_fixture(
        dtype,
        extra=extra,
        limits=policy(
            max_working_bytes=16_000_000,
            max_live_array_bytes=8_000_000,
            max_decoded_bytes=8_000_000,
        ),
    )
    scope, runtime, cloud, groups, pose, _, rotation, origin = values

    def window(name, center, size):
        return dict(
            roi_id=name,
            rois=[
                dict(
                    roi_id=name,
                    frame_id="fixture",
                    length_unit="mm",
                    kind="box",
                    geometry=dict(
                        center=origin + rotation @ center, size=size, rotation=rotation
                    ),
                )
            ],
        )

    p = extract_parameters(
        evaluation=dict(
            kind="pose",
            frame_id="fixture",
            length_unit="mm",
            pose_id="datum",
            target_frame_id="part",
        ),
        method=dict(
            kind="pose-contour",
            reference_feature_id="reference",
            height=dict(
                kind="measurement-ratio",
                item_id="step",
                reference_feature_id="reference",
                target_feature_id="target",
                ratio=0.5,
                order="target-above",
            ),
            numeric_tolerance=1e-8,
        ),
        region=window("all", [17, 0, 2], [15, 5, 5]),
        surface=dict(
            alpha_radius=0.8,
            max_edge_length=1.5,
            max_normal_step=2,
            min_projected_area=0.001,
        ),
        targets=[
            dict(
                segment_id=name,
                region=window(name, [x, 0, 2], [5, 5, 5]),
                closed=False,
                role="open",
            )
            for name, x in (("left", 12), ("right", 22))
        ],
    )
    measured = measure_step(
        runtime,
        step_parameters(query=query()),
        groups=groups,
        pose=pose,
        cancel=lambda: None,
    )
    return values, p, measured.items[0]


def extract(values, p, measurement):
    """只连接真实拟合及测量结果，不替换来源准入。"""
    _, runtime, cloud, groups, pose, *_ = values
    planes = {g.items[0].feature_id: g.items[0] for g in groups}
    selected = (
        tuple(
            planes[key]
            for key in (
                p.method.height.reference_feature_id,
                p.method.height.target_feature_id,
            )
        )
        if measurement is not None and p.method.height.kind == "measurement-ratio"
        else ()
    )
    return extract_boundary(
        runtime,
        cloud,
        p,
        contour_plane=groups[0].items[0],
        pose=pose,
        measurement=measurement,
        measurement_planes=selected,
        cancel=lambda: None,
    )


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_tilted_ratio_line_extents_and_edge_pair_truth(dtype):
    values, p, measurement = fixture(dtype)
    scope, runtime, _, _, _, _, rotation, origin = values
    try:
        boundary = extract(values, p, measurement)
        b = boundary.items[0]
        assert b.valid, b.reason
        tolerance = 4e-6 if dtype == np.float32 else 1e-10
        assert b.method.resolution.height == pytest.approx(2.525, abs=tolerance)
        np.testing.assert_allclose(
            b.method.resolution.evaluation.origin,
            origin + rotation @ [0, 0, 2.525],
            atol=tolerance,
            rtol=0,
        )
        lines = []
        for name in ("left", "right"):
            fit = fit_boundary(
                runtime,
                boundary,
                line_parameters(
                    feature_id=name,
                    selection=dict(feature_id="boundary", segment_ids=[name]),
                    evaluation=inherited(),
                    positive_direction=dict(kind="axis", axis="v"),
                ),
                cancel=lambda: None,
            )
            assert fit.items[0].valid, fit.items[0].reason
            lines.append(fit)
        extent = measure_extents(
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
            groups=[boundary],
            cancel=lambda: None,
        )
        assert [i.value for i in extent.items] == pytest.approx([10, 4], abs=tolerance)
        pair = measure_edge_pair(
            runtime,
            lines,
            pair_parameters(
                reference_feature_id="left",
                target_feature_id="right",
                evaluation=inherited(),
                query_position=dict(kind="plane-uv", uv=[0, 0]),
                direction=dict(kind="axis", axis="u"),
            ),
            cancel=lambda: None,
        )
        assert pair.items[0].valid and pair.items[0].value == pytest.approx(
            10, abs=tolerance
        )
        np.testing.assert_allclose(
            pair.items[0].geometry.endpoints,
            [origin + rotation @ [x, 0, 2.525] for x in (12.525, 22.525)],
            atol=tolerance,
            rtol=0,
        )
        # 原底面上的配置模式仍受原面外残差限制，不放宽门禁来接受错误评价面。
        wrong = fit_boundary(
            runtime,
            boundary,
            line_parameters(
                selection=dict(feature_id="boundary", segment_ids=["left"]),
                evaluation=evaluation(origin=origin, rotation=rotation),
                positive_direction=rotation[:, 1],
            ),
            cancel=lambda: None,
        )
        assert (
            not wrong.items[0].valid and wrong.items[0].reason == "insufficient_quality"
        )
        assert MeasurementEvidence3d.model_validate_json(pair.model_dump_json()) == pair
        raw = b.model_dump(exclude={"support"}, mode="json")
        assert not any(key in str(raw) for key in ('"run_id"', '"cloud_id"', '"lease"'))
        saved = BoundaryEvidence.model_validate(raw)
        changed = deepcopy(raw)
        changed["method"]["resolution"]["height"] += 0.1
        with pytest.raises(ValidationError, match="等高解析"):
            BoundaryEvidence.model_validate(changed)
    finally:
        assert not scope.close() and runtime.budget.used == 0
    assert BoundaryEvidence.model_validate_json(saved.model_dump_json()) == saved


def test_order_and_fixed_height_do_not_fallback():
    values, p, measurement = fixture()
    scope, runtime, *_ = values
    try:
        raw = p.model_dump(mode="json")
        raw["method"]["height"]["order"] = "target-below"
        failed = extract(
            values, ExtractBoundaryParameters.model_validate(raw), measurement
        ).items[0]
        assert not failed.valid and failed.reason == "contour_height_order"
        assert (
            failed.method.resolution.height is None
            and failed.method.resolution.evaluation is None
        )
        fitted = fit_boundary(
            runtime,
            Features3d(
                run_id=runtime.run_id,
                observation_id=failed.support.observation_id,
                frame_id="fixture",
                length_unit="mm",
                items=[failed],
            ),
            line_parameters(
                selection=dict(feature_id="boundary", segment_ids=["left"]),
                evaluation=inherited(),
                positive_direction=dict(kind="axis", axis="v"),
            ),
            cancel=lambda: None,
        )
        assert not fitted.items[0].valid and fitted.items[0].method.evaluation is None
        raw["method"]["height"] = dict(kind="fixed", value=1.25)
        fixed = extract(
            values, ExtractBoundaryParameters.model_validate(raw), None
        ).items[0]
        assert fixed.valid and fixed.method.resolution.height == 1.25
        with pytest.raises(InvalidRequestError, match="固定等高"):
            extract(values, ExtractBoundaryParameters.model_validate(raw), measurement)
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_negative_order_keeps_roles_and_same_midplane():
    values, p, _ = fixture()
    scope, runtime, _, groups, pose, *_ = values
    try:
        raw = step_parameters(query=query()).model_dump(mode="json")
        raw["mode"].update(reference_feature_id="target", target_feature_id="reference")
        measurement = measure_step(
            runtime,
            type(step_parameters()).model_validate(raw),
            groups=groups,
            pose=pose,
            cancel=lambda: None,
        ).items[0]
        assert measurement.valid and measurement.value == pytest.approx(-5.05)
        config = p.model_dump(mode="json")
        config["method"]["height"].update(
            reference_feature_id="target",
            target_feature_id="reference",
            order="target-below",
        )
        boundary = extract(
            values, ExtractBoundaryParameters.model_validate(config), measurement
        ).items[0]
        assert boundary.valid and boundary.method.resolution.height == pytest.approx(
            2.525
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize("order", ["target-above", "target-below"])
def test_coincident_planes_reject_both_orders(order):
    """相同真实支持拟成两个命名面，高差为零不能当成任一方向的等高。"""
    values, p, _ = fixture()
    scope, runtime, _, groups, pose, _, rotation, _ = values
    try:
        target = fit_plane(
            runtime,
            groups[0].items[0].support,
            plane_parameters(feature_id="target", positive_normal=rotation[:, 2]),
            cancel=lambda: None,
        )
        groups[1] = target
        measurement = measure_step(
            runtime,
            step_parameters(query=query()),
            groups=groups,
            pose=pose,
            cancel=lambda: None,
        ).items[0]
        assert measurement.valid and measurement.value == 0
        raw = p.model_dump(mode="json")
        raw["method"]["height"]["order"] = order
        result = extract(values, type(p).model_validate(raw), measurement).items[0]
        assert not result.valid and result.reason == "contour_height_order"
        assert result.method.resolution.evaluation is None
        assert result.method.resolution.height is None
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_tampered_measurement_source_is_rejected_before_geometry():
    values, p, measurement = fixture()
    scope, runtime, *_ = values
    try:
        raw = measurement.model_dump(mode="json")
        raw["support"][1]["content_sha256"] = "a" * 64
        changed = type(measurement).model_validate(raw)
        before = runtime.budget.used
        with pytest.raises(InvalidRequestError, match="完整支持"):
            extract(values, p, changed)
        assert runtime.budget.used == before
        for ratio in (0, 1, -1):
            config = p.model_dump(mode="json")
            config["method"]["height"]["ratio"] = ratio
            with pytest.raises(ValidationError):
                ExtractBoundaryParameters.model_validate(config)
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_fixed_contour_circle_inheritance_has_independent_radius():
    """截面穿过解析 r=4 环，继承倾斜面后直径必须为8，不再次拟合。"""
    angle = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    extra = [
        (20 + radius * np.cos(t), 12 + radius * np.sin(t), z)
        for radius, z in ((3, 0), (4, 1.25), (5, 2.5))
        for t in angle
    ]
    values = tilted_fixture(
        extra=extra,
        limits=policy(
            max_working_bytes=16_000_000,
            max_live_array_bytes=8_000_000,
            max_decoded_bytes=8_000_000,
        ),
    )
    scope, runtime, cloud, groups, pose, _, rotation, origin = values
    window = dict(
        roi_id="ring",
        rois=[
            dict(
                roi_id="ring",
                frame_id="fixture",
                length_unit="mm",
                kind="box",
                geometry=dict(
                    center=origin + rotation @ [20, 12, 1.25],
                    size=[12, 12, 4],
                    rotation=rotation,
                ),
            )
        ],
    )
    p = extract_parameters(
        evaluation=dict(
            kind="pose",
            frame_id="fixture",
            length_unit="mm",
            pose_id="datum",
            target_frame_id="part",
        ),
        method=dict(
            kind="pose-contour",
            reference_feature_id="reference",
            height=dict(kind="fixed", value=1.25),
            numeric_tolerance=1e-8,
        ),
        region=window,
        surface=dict(
            alpha_radius=2,
            max_edge_length=2,
            max_normal_step=2,
            min_projected_area=1e-5,
        ),
        targets=[dict(segment_id="arc", region=window, closed=True, role="outer")],
    )
    try:
        boundary = extract(values, p, None)
        assert boundary.items[0].valid, boundary.items[0].reason
        circle = fit_boundary(
            runtime,
            boundary,
            circle_parameters(evaluation=inherited()),
            cancel=lambda: None,
        )
        assert circle.items[0].valid, circle.items[0].reason
        assert circle.items[0].geometry.radius == pytest.approx(4, abs=1e-10)
        np.testing.assert_allclose(
            circle.items[0].geometry.center,
            origin + rotation @ [20, 12, 1.25],
            atol=1e-10,
        )
        rejected = measure_hole(
            runtime,
            [circle],
            hole_parameters(
                evaluation=inherited(),
                target_kind="open-arc",
                display_direction=dict(kind="axis", axis="-u"),
            ),
            cancel=lambda: None,
        )
        assert (
            not rejected.items[0].valid
            and rejected.items[0].reason == "invalid_boundary_role"
        )
        raw = p.model_dump(mode="json")
        raw["targets"][0].update(closed=False, role="open")
        raw["targets"][0]["region"]["rois"][0]["geometry"].update(
            center=(origin + rotation @ [20, 15, 1.25]).tolist(), size=[12, 6, 4]
        )
        arc = extract(values, type(p).model_validate(raw), None)
        assert arc.items[0].valid, arc.items[0].reason
        circle = fit_boundary(
            runtime, arc, circle_parameters(evaluation=inherited()), cancel=lambda: None
        )
        measured = measure_hole(
            runtime,
            [circle],
            hole_parameters(
                evaluation=inherited(),
                target_kind="open-arc",
                display_direction=dict(kind="axis", axis="-u"),
            ),
            cancel=lambda: None,
        )
        assert measured.items[0].valid and measured.items[0].value == pytest.approx(
            8, abs=1e-10
        )
        assert (
            MeasurementEvidence3d.model_validate_json(measured.model_dump_json())
            == measured
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_invalid_measurement_and_cancel_never_reuse_height():
    """真实支持外测量失败，不能沿用上次有效高度；取消后 Scope 回收全部。"""
    values, p, measurement = fixture()
    scope, runtime, cloud, groups, pose, *_ = values
    try:
        assert extract(values, p, measurement).items[0].valid
        failed = measure_step(
            runtime,
            step_parameters(query=query((100, 100))),
            groups=groups,
            pose=pose,
            cancel=lambda: None,
        ).items[0]
        assert not failed.valid
        boundary = extract(values, p, failed).items[0]
        assert (
            not boundary.valid and boundary.reason == "contour_measurement_unavailable"
        )
        assert boundary.method.resolution.height is None
        assert boundary.method.resolution.evaluation is None

        def cancel():
            raise InterruptedError("cancel-test")

        with pytest.raises(InterruptedError):
            extract_boundary(
                runtime,
                cloud,
                p,
                contour_plane=groups[0].items[0],
                pose=pose,
                measurement=measurement,
                measurement_planes=tuple(g.items[0] for g in groups),
                cancel=cancel,
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_source_from_another_run_is_rejected():
    """相同坐标和同名特征不等于同次运行的授权。"""
    values, p, measured = fixture()
    other, _, _ = fixture()
    try:
        with pytest.raises(InvalidRequestError):
            extract(other, p, measured)
        replaced = list(values)
        replaced[4] = other[4]
        with pytest.raises(InvalidRequestError):
            extract(replaced, p, measured)
    finally:
        for item in (values, other):
            assert not item[0].close() and item[1].budget.used == 0
