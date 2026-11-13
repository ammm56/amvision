"""B13 公开证据往返、量值单位、损坏拒绝与失败来源。"""

import numpy as np
import pytest
from math import atan
from pydantic import ValidationError

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from custom_nodes.metrology3d_nodes.shared.relation_result import relation_evidence
from tests.test_metrology3d_dimension_runtime import analytic_edges, analytic_circle
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_relations import parameters
from tests.test_metrology3d_height_step import two_planes
from custom_nodes.metrology3d_nodes.shared.measurement_preview import (
    attach_measurements,
)
from custom_nodes.metrology3d_nodes.shared.preview import build_cloud_preview
from tests.test_metrology3d_preview import preview_policy
from backend.service.application.errors import InvalidRequestError
from tests.test_metrology3d_dimension_runtime import ordered


@pytest.mark.parametrize(
    "method", ["point-point", "point-line", "line-line", "line-angle"]
)
def test_relation_evidence_roundtrip_units_and_tamper(method):
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[0, -2, 0], [0, 2, 0], [4, -2, 0], [4, 2, 0]], dtype=float
        ),
    )
    try:
        groups = [analytic_edges(runtime, cloud)]
        p = parameters(method)
        result = relation_evidence(runtime, cloud, groups, p, cancel=lambda: None)
        restored = MeasurementEvidence3d.model_validate_json(result.model_dump_json())
        assert restored == result
        numeric = restored.numeric_table().items[0]
        assert numeric.unit == ("rad" if method == "line-angle" else "mm")
        assert numeric.value == restored.items[0].value
        assert (
            "cloud_id" not in result.model_dump_json()
            and "run_id" not in result.model_dump_json()
        )
        raw = result.model_dump(mode="json")
        raw["items"][0]["value"] += 1
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
        configured = preview_policy(max_body_bytes=262144)
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=4, color=dict(mode="solid")),
            policy=configured,
            cancel=lambda: None,
        )
        displayed = attach_measurements(
            cloud,
            body,
            {"evidence": [result.model_dump(mode="json")]},
            policy=configured,
            cancel=lambda: None,
        )
        assert displayed["measurements"] == result.model_dump(mode="json")
        raw = result.model_dump(mode="json")
        raw["items"][0]["method"]["parameters_sha256"] = "f" * 64
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_circle_point_preserves_original_model():
    angle = np.arange(8) * np.pi / 4
    xyz = np.column_stack((4 * np.cos(angle), 4 * np.sin(angle), np.zeros(8)))
    scope, runtime, cloud = make_cloud(unit="mm", coordinates=xyz)
    try:
        group = analytic_circle(runtime, cloud)
        p = parameters(
            reference=dict(kind="circle-center", feature_id="circle"),
            target=dict(kind="coordinate", position=(3, 4, 0)),
        )
        result = relation_evidence(runtime, cloud, [group], p, cancel=lambda: None)
        assert result.items[0].value == 5
        assert result.items[0].support[0].feature.kind == "circle"
        assert (
            MeasurementEvidence3d.model_validate_json(result.model_dump_json())
            == result
        )
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_plane_support_roundtrip_and_quality_not_bypassed():
    scope, runtime, cloud, _, _, groups = two_planes()
    try:
        p = parameters(
            "point-plane",
            target=dict(kind="plane", feature_id="reference"),
            reference=dict(kind="coordinate", position=(0, 0, 5)),
            support_mode="finite",
            coverage=dict(
                support_radius=2,
                min_support_count=3,
                max_triangle_edge=2,
                max_plane_residual=0.01,
            ),
        )
        result = relation_evidence(runtime, cloud, groups, p, cancel=lambda: None)
        assert result.items[0].value == 5
        assert (
            MeasurementEvidence3d.model_validate_json(result.model_dump_json())
            == result
        )
        raw = result.model_dump(mode="json")
        raw["items"][0]["support"][1]["coverage"]["max_residual"] = 4
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
        raw = p.model_dump(mode="json")
        raw["relation"]["reference"]["position"] = [20, 0, 5]
        failed = relation_evidence(
            runtime, cloud, groups, type(p).model_validate(raw), cancel=lambda: None
        )
        assert not failed.items[0].valid and failed.items[0].value is None
        assert failed.items[0].diagnostic.role == "target"
        assert failed.items[0].support[1].coverage is not None
        assert (
            MeasurementEvidence3d.model_validate_json(failed.model_dump_json())
            == failed
        )
        raw = failed.model_dump(mode="json")
        raw["items"][0]["diagnostic"]["stage"] = "source"
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_plane_angle_preserves_independent_supports_and_original_quality():
    scope, runtime, cloud, _, _, groups = two_planes(slope=0.25)
    try:
        p = parameters(
            "plane-angle",
            reference=dict(kind="plane", feature_id="reference"),
            target=dict(kind="plane", feature_id="target"),
        )
        result = relation_evidence(runtime, cloud, groups, p, cancel=lambda: None)
        item = result.items[0]
        assert item.value == pytest.approx(atan(0.25), abs=1e-12)
        assert item.support[0].content_sha256 != item.support[1].content_sha256
        assert item.geometry.endpoints is None and item.geometry.contacts_unique is None
        assert (
            MeasurementEvidence3d.model_validate_json(result.model_dump_json())
            == result
        )
        raw = result.model_dump(mode="json")
        raw["items"][0]["support"][1]["plane"]["quality"]["metrics"][
            "observation_id"
        ] = "another-observation"
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_quality_failure_keeps_both_supports_but_no_value_or_endpoints():
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[0, -2, 0], [0, 2, 0], [4, -2, 0], [4, 2, 0]], dtype=float
        ),
    )
    try:
        group = analytic_edges(runtime, cloud)
        raw = parameters("line-line", support_mode="finite").model_dump(mode="json")
        raw["quality_policy"]["rules"].append(
            dict(item_id="contacts_unique", unit="1", lower=1)
        )
        p = type(parameters()).model_validate(raw)
        evidence = relation_evidence(runtime, cloud, [group], p, cancel=lambda: None)
        item = evidence.items[0]
        assert not item.valid and item.value is None and item.geometry is None
        assert item.diagnostic.stage == "quality" and item.diagnostic.role is None
        assert all(side.feature.valid for side in item.support)
        assert (
            MeasurementEvidence3d.model_validate_json(evidence.model_dump_json())
            == evidence
        )
        tampered = evidence.model_dump(mode="json")
        tampered["items"][0]["diagnostic"]["role"] = "target"
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(tampered)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_missing_source_is_preserved_and_cannot_claim_a_successful_geometry():
    scope, runtime, cloud = make_cloud(unit="mm")
    try:
        p = parameters(reference=dict(kind="source-point", source_index=100))
        # 越出原始总数属于输入错误，不伪装成有效结果或普通缺测。
        with pytest.raises(InvalidRequestError):
            relation_evidence(runtime, cloud, [], p, cancel=lambda: None)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_forged_coverage_pass_is_rejected_by_existing_comparator():
    scope, runtime, cloud, _, _, groups = two_planes()
    try:
        p = parameters(
            "point-plane",
            target=dict(kind="plane", feature_id="reference"),
            reference=dict(kind="coordinate", position=(0, 0, 5)),
            support_mode="finite",
            coverage=dict(
                support_radius=2,
                min_support_count=3,
                max_triangle_edge=2,
                max_plane_residual=0.01,
            ),
        )
        result = relation_evidence(runtime, cloud, groups, p, cancel=lambda: None)
        raw = result.model_dump(mode="json")
        quality = raw["items"][0]["support"][1]["coverage_quality"]
        # 保持结构和数值不变，篡改一个逐项比较为失败。
        quality["checks"][0].update(passed=False, reason="below_lower")
        quality["usable"] = False
        # 有效量值不允许携带失败覆盖；读取阶段先拒绝，不能沿用有效数值。
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
        forged = result.model_dump(mode="json")
        side = forged["items"][0]["support"][1]
        side["coverage"]["triangle_edge"] = 30
        for metric in side["coverage_quality"]["metrics"]["items"]:
            if metric["item_id"] == "triangle_edge":
                metric["value"] = 30
        for check in side["coverage_quality"]["checks"]:
            if check["item_id"] == "triangle_edge":
                check["value"] = 30
        # 结构校验不复制限值比较器；消费时必须复用已有比较器拒绝伪造 passed。
        MeasurementEvidence3d.model_validate(forged)
        configured = preview_policy(max_body_bytes=262144)
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=4, color=dict(mode="solid")),
            policy=configured,
            cancel=lambda: None,
        )
        with pytest.raises(InvalidRequestError, match="实际限值"):
            attach_measurements(
                cloud,
                body,
                {"evidence": [forged]},
                policy=configured,
                cancel=lambda: None,
            )
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_missing_subset_row_keeps_invalid_evidence_and_cancellation_releases_borrows():
    scope, runtime, root = make_cloud(
        unit="mm", coordinates=np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=float)
    )
    try:
        cloud = ordered(
            runtime,
            root,
            [2, 0],
            [
                dict(
                    segment_id="selected",
                    start=0,
                    count=2,
                    closed=False,
                    role="open",
                    orientation="open",
                )
            ],
        )
        p = parameters(reference=dict(kind="source-point", source_index=1))
        evidence = relation_evidence(runtime, cloud, [], p, cancel=lambda: None)
        item = evidence.items[0]
        assert item.reason == "source_point_not_in_support"
        assert item.diagnostic.stage == "source" and item.diagnostic.role == "reference"
        assert item.support[0].point.source_index == 1
        assert item.support[0].point.logical_index is None
        assert item.support[0].source_point_count == 3
        assert (
            MeasurementEvidence3d.model_validate_json(evidence.model_dump_json())
            == evidence
        )
        before = runtime.budget.used
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 8:
                raise InterruptedError("cancelled")

        with pytest.raises(InterruptedError):
            relation_evidence(runtime, cloud, [], p, cancel=cancel)
        assert runtime.budget.used == before
        assert relation_evidence(runtime, cloud, [], p, cancel=lambda: None) == evidence
    finally:
        assert scope.close() == () and runtime.budget.used == 0
