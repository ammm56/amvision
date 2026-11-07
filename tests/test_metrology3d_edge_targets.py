"""B09 目标级诊断、既有段/组选择和逐段质量，独立解析行号真值。"""

import numpy as np
import pytest

from backend.contracts.workflows.edge3d_selection import (
    EdgeTargetSelection,
    EdgeTargetReport,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_chains import build_edge_chains
from custom_nodes.metrology3d_nodes.shared.edge_targets import select_edge_targets
from tests.integration.metrology3d.representative_recipe import boxes
from tests.test_metrology3d_edge_chains import prepare, chain_settings


def selection(*regions, length=0.01):
    """两点/正长度是解析场景的显式测试限值，不进入生产默认。"""
    return EdgeTargetSelection.model_validate(
        dict(
            targets=[
                dict(
                    segment_id=f"edge-{i}",
                    region=boxes(f"roi-{i}", [r]),
                    closed=False,
                    role="open",
                )
                for i, r in enumerate(regions or [[1.7, 1.9, -1, 5, 1.9, 2.1]])
            ],
            min_projected_area=0.001,
            quality_policy=dict(
                policy_id="edge-quality",
                policy_version=1,
                rules=[
                    dict(item_id="support_count", unit="1", lower=2),
                    dict(item_id="length", unit="mm", lower=length),
                    dict(item_id="max_planar_gap", unit="mm", upper=0.65),
                ],
            ),
        )
    )


@pytest.mark.parametrize("dtype,chunk", [("float32", 1), ("float64", 32)])
def test_target_keeps_all_source_rows_and_quality(dtype, chunk):
    scope, runtime, _, _, _, pairs = prepare(dtype=dtype, rows=chunk)
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        baseline = runtime.budget.used
        result = select_edge_targets(runtime, chains, selection(), cancel=lambda: None)
        assert result.reason is None
        report = EdgeTargetReport.model_validate_json(result.reports_json[0])
        assert report.topology.segments[0].segment_id == "edge-0"
        assert report.quality.usable and report.segments[0].quality.usable
        assert report.topology.point_count == 15
        length = next(
            v.value for v in report.quality.metrics.items if v.item_id == "length"
        )
        np.testing.assert_allclose(length, 4.4, atol=1e-6)
        with result.borrow(runtime) as arrays, chains.borrow(runtime) as chain:
            np.testing.assert_array_equal(
                arrays["source_rows"], chain["source_rows"][arrays["chain_rows"][:, 0]]
            )
            assert all(not a.flags.writeable for a in arrays.values())
        runtime.storage_scope.close_resource(result.resource_key)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_multiple_fragments_not_longest_and_target_failure_is_named():
    scope, runtime, _, _, _, pairs = prepare()
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(distance=0.5), cancel=lambda: None
        )
        result = select_edge_targets(
            runtime,
            chains,
            selection([1.7, 1.9, -0.3, 0.3, 1.9, 2.1], [1.7, 1.9, 0.7, 5, 1.9, 2.1]),
            cancel=lambda: None,
        )
        first, second = map(EdgeTargetReport.model_validate_json, result.reports_json)
        assert first.reason is None and first.topology.point_count == 3
        assert (
            second.reason == result.reason == "target_ambiguous"
            and second.target_id == "edge-1"
        )
        with result.borrow(runtime) as data:
            assert data["offsets"][:, 0].tolist() == [0, 3, 3]
    finally:
        assert scope.close() == ()


def test_quality_failure_not_hidden_by_geometric_selection():
    scope, runtime, _, _, _, pairs = prepare()
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        result = select_edge_targets(
            runtime, chains, selection(length=10), cancel=lambda: None
        )
        report = EdgeTargetReport.model_validate_json(result.reports_json[0])
        assert result.reason == "insufficient_quality"
        assert report.topology is None and not report.segments[0].quality.usable
        with result.borrow(runtime) as data:
            assert len(data["source_rows"]) == 0
    finally:
        assert scope.close() == ()


def test_diagnostic_inside_target_rejects_but_outside_does_not(monkeypatch):
    from custom_nodes.metrology3d_nodes.shared import edge_chains

    scope, runtime, _, _, _, pairs = prepare()
    original = edge_chains._build

    def with_issue(*args, **kwargs):
        value = original(*args, **kwargs)
        kwargs["issues"].add((7, 1))
        return (*value[:-1], "pairing_ambiguous")

    monkeypatch.setattr(edge_chains, "_build", with_issue)
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        assert chains.reason == "pairing_ambiguous"
        result = select_edge_targets(
            runtime,
            chains,
            selection([1.7, 1.9, -0.3, 0.3, 1.9, 2.1], [1.7, 1.9, 1.7, 2.3, 1.9, 2.1]),
            cancel=lambda: None,
        )
        first, second = map(EdgeTargetReport.model_validate_json, result.reports_json)
        assert first.reason is None and first.topology.point_count == 3
        assert second.reason == "pairing_ambiguous"
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("phase", [1, 10, 30])
def test_target_cancellation_and_parent_release(phase):
    scope, runtime, _, _, _, pairs = prepare(rows=1)
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        baseline = runtime.budget.used
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == phase:
                raise InterruptedError("cancel-target")

        with pytest.raises(InterruptedError):
            select_edge_targets(runtime, chains, selection(), cancel=cancel)
        assert runtime.budget.used == baseline
        result = select_edge_targets(runtime, chains, selection(), cancel=lambda: None)
        runtime.storage_scope.close_resource(chains.resource_key)
        with pytest.raises(InvalidRequestError):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()


def test_budget_and_space_reject_before_output():
    scope, runtime, _, _, _, pairs = prepare()
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        baseline = runtime.budget.used
        raw = selection().model_dump_json()
        bad = EdgeTargetSelection.model_validate_json(
            raw.replace('"fixture"', '"wrong"')
        )
        with pytest.raises(InvalidRequestError, match="空间"):
            select_edge_targets(runtime, chains, bad, cancel=lambda: None)
        runtime.policy = runtime.policy.model_copy(update={"max_working_bytes": 1024})
        with pytest.raises(InvalidRequestError, match="预算"):
            select_edge_targets(runtime, chains, selection(), cancel=lambda: None)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("minimum,expected", [(2, None), (4, "insufficient_quality")])
def test_fragment_quality_and_group_length_do_not_bridge_gaps(minimum, expected):
    scope, runtime, _, _, _, pairs = prepare()
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(distance=0.5), cancel=lambda: None
        )
        raw = selection().model_dump()
        target = raw["targets"][0]
        fragment_policy = dict(
            policy_id="fragment-check",
            policy_version=1,
            rules=[
                dict(item_id="support_count", unit="1", lower=minimum),
                dict(item_id="length", unit="mm", lower=0.1),
            ],
        )
        raw["targets"] = [
            dict(
                group_id="edge-group",
                region=target["region"],
                role="open",
                arc=dict(
                    center=(0, 0),
                    radius_range=(0.1, 20),
                    start_angle=1.5 * np.pi,
                    sweep=np.pi,
                    max_overlap_angle=0.01,
                ),
                fragment_quality_policy=fragment_policy,
            )
        ]
        result = select_edge_targets(
            runtime,
            chains,
            EdgeTargetSelection.model_validate(raw),
            cancel=lambda: None,
        )
        report = EdgeTargetReport.model_validate_json(result.reports_json[0])
        assert result.reason == expected
        assert len(report.segments) == 5 and report.quality.usable
        assert all(s.quality.usable == (minimum == 2) for s in report.segments)
        length = next(
            i.value for i in report.quality.metrics.items if i.item_id == "length"
        )
        np.testing.assert_allclose(length, 2, atol=1e-12)
        if minimum == 2:
            assert {s.group_id for s in report.topology.segments} == {"edge-group"}
    finally:
        assert scope.close() == ()


def test_duplicate_targets_do_not_consume_same_points_twice():
    scope, runtime, _, _, _, pairs = prepare()
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        result = select_edge_targets(
            runtime,
            chains,
            selection([1.7, 1.9, -1, 5, 1.9, 2.1], [1.7, 1.9, -1, 5, 1.9, 2.1]),
            cancel=lambda: None,
        )
        assert result.reason == "target_conflict"
        with result.borrow(runtime) as data:
            assert data["offsets"][:, 0].tolist() == [0, 15, 15]
    finally:
        assert scope.close() == ()


def test_cancel_after_owner_registration_rolls_back():
    scope, runtime, _, _, _, pairs = prepare()
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        baseline = runtime.budget.used

        def cancel():
            if runtime.budget.used > baseline:
                raise InterruptedError("after-owner")

        with pytest.raises(InterruptedError, match="after-owner"):
            select_edge_targets(runtime, chains, selection(), cancel=cancel)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_evaluation_inverse_pose_uses_source_coordinates():
    """手算 90 度旋转加平移的格基，避免被测变换生成期望。"""
    from types import SimpleNamespace as N
    from custom_nodes.metrology3d_nodes.shared.edge_targets import height_evaluation

    reference = N(
        cloud=N(spatial=N(frame_id="source", length_unit="mm")),
        evidence=N(
            parameters=N(
                grid=N(
                    column_direction=(1, 0, 0),
                    row_direction=(0, 1, 0),
                    height_direction=(0, 0, 1),
                    origin=(8, 23, 35),
                )
            ),
            pose=N(
                transform=N(
                    matrix=[
                        [0, -1, 0, 10],
                        [1, 0, 0, 20],
                        [0, 0, 1, 30],
                        [0, 0, 0, 1],
                    ]
                )
            ),
        ),
    )
    actual = height_evaluation(reference)
    np.testing.assert_array_equal(actual.origin, (3, 2, 5))
    np.testing.assert_array_equal(actual.rotation, [[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
    assert actual.frame_id == "source"


@pytest.mark.parametrize("field,value", [("item_id", "unknown"), ("unit", "m")])
def test_bad_quality_rejected_even_when_target_is_empty(field, value):
    scope, runtime, _, _, _, pairs = prepare()
    try:
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        raw = selection([100, 101, 100, 101, 100, 101]).model_dump()
        raw["quality_policy"]["rules"][2][field] = value
        baseline = runtime.budget.used
        with pytest.raises(InvalidRequestError, match="未知指标或错误单位"):
            select_edge_targets(
                runtime,
                chains,
                EdgeTargetSelection.model_validate(raw),
                cancel=lambda: None,
            )
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()
