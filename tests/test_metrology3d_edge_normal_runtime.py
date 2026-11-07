"""法向实测侧、有限连续段和目标质量，使用已有 B03 实际输出。"""

import numpy as np
import pytest

from backend.contracts.workflows.edge3d import NormalEdgeSettings
from backend.contracts.workflows.edge3d_selection import (
    EdgeTargetSelection,
    EdgeTargetReport,
)
from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_pairing import (
    pair_normal_points,
    PairStatus,
)
from custom_nodes.metrology3d_nodes.shared.edge_normal_candidates import (
    normal_crease_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_normal_runtime import (
    pair_normal_candidates,
    build_normal_edge_chains,
)
from custom_nodes.metrology3d_nodes.shared.edge_targets import select_edge_targets
from tests.test_metrology3d_edge_normals import prepare
from tests.test_metrology3d_edge_targets import selection


def options(side="a", **kwargs):
    """显式测试的连接/等距条件，不进入生产默认。"""
    return NormalEdgeSettings(
        side=side,
        tie_tolerance=1e-8,
        max_link_distance=kwargs.get("distance", 0.25),
        max_turn_angle=0.2,
    )


def evaluation():
    """测试配方明确给出源空间评价面。"""
    return EvaluationPlane3d(
        frame_id="fixture",
        length_unit="mm",
        origin=(0, 0, 0),
        rotation=np.eye(3).tolist(),
    )


def targets(side="a", length=0.1):
    """只选实际边排，不把两侧拟面支持 ROI 当边位置。"""
    region = (
        [-0.21, -0.19, -1.1, 1.1, -0.01, 0.01]
        if side == "a"
        else [0.09, 0.11, -1.1, 1.1, 0.17, 0.18]
    )
    raw = selection(region, length=length).model_dump()
    raw["quality_policy"]["rules"][2].update(item_id="max_pair_distance", upper=0.38)
    return EdgeTargetSelection.model_validate(raw)


@pytest.mark.parametrize("side", ["a", "b"])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_analytic_fold_actual_side_chain_and_quality(side, dtype):
    scope, runtime, _, cloud, settings = prepare(dtype=dtype)
    try:
        candidates = normal_crease_candidates(
            runtime, cloud, settings, cancel=lambda: None
        )
        pairs = pair_normal_candidates(
            runtime, candidates, options(side), cancel=lambda: None
        )
        chains = build_normal_edge_chains(runtime, pairs, cancel=lambda: None)
        result = select_edge_targets(
            runtime, chains, targets(side), evaluation=evaluation(), cancel=lambda: None
        )
        report = EdgeTargetReport.model_validate_json(result.reports_json[0])
        assert report.reason is None, report.model_dump()
        assert report.quality.usable and report.topology.point_count == 11
        metric = {v.item_id: v.value for v in report.quality.metrics.items}
        np.testing.assert_allclose(metric["length"], 2, atol=1e-7)
        np.testing.assert_allclose(
            metric["max_pair_distance"], np.sqrt(0.12), atol=1e-7
        )
        assert "max_planar_gap" not in metric
        with result.borrow(runtime) as data:
            expected = np.arange(11) + (0 if side == "a" else 55)
            np.testing.assert_array_equal(np.sort(data["source_rows"][:, 0]), expected)
        with pairs.borrow(runtime) as data:
            assert np.isnan(data["metrics"][:, (0, 2)]).all()
            assert len(data["source_rows"]) == cloud.point_count
        for resource in (result, chains, pairs, candidates):
            runtime.storage_scope.close_resource(resource.resource_key)
    finally:
        assert scope.close() == ()


def test_missing_link_is_not_filled_or_replaced_by_longest_segment():
    scope, runtime, _, cloud, settings = prepare()
    try:
        candidates = normal_crease_candidates(
            runtime, cloud, settings, cancel=lambda: None
        )
        pairs = pair_normal_candidates(
            runtime, candidates, options(distance=0.1), cancel=lambda: None
        )
        chains = build_normal_edge_chains(runtime, pairs, cancel=lambda: None)
        result = select_edge_targets(
            runtime, chains, targets(), evaluation=evaluation(), cancel=lambda: None
        )
        assert result.reason == "target_ambiguous"
        with result.borrow(runtime) as data:
            assert len(data["source_rows"]) == 0
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("rotate", [False, True])
def test_pairing_matches_full_distance_truth_and_has_no_height_axis(rotate):
    """完整距离矩阵验证三维互近邻，不使用被测索引生成期望。"""
    from tests.test_metrology3d_edge_support import fold, crease_settings

    points, masks = fold(np.pi / 3)
    normals = np.asarray([[0, 0, 1], [-np.sin(np.pi / 3), 0, np.cos(np.pi / 3)]])
    origins = np.zeros((2, 3))
    if rotate:
        points = points[:, (2, 0, 1)] + (10, 20, 30)
        normals = normals[:, (2, 0, 1)]
        origins += (10, 20, 30)
    support = crease_settings()
    side, state, partner, metrics = pair_normal_points(
        points, origins, normals, support, options(), chunk_rows=3, cancel=lambda: None
    )
    np.testing.assert_array_equal(side, np.where(masks[:, 0], 0, 1))
    a, b = (np.flatnonzero(masks[:, n]) for n in range(2))
    distance = np.linalg.norm(points[a, None] - points[b], axis=2)
    for i, row in enumerate(a):
        j = int(np.argmin(distance[i]))
        mutual = (
            int(np.argmin(distance[:, j])) == i
            and distance[i, j] <= support.max_pair_distance
        )
        assert (state[row] == PairStatus.PAIRED) == mutual
        if mutual:
            assert partner[row] == b[j] and partner[b[j]] == row
            np.testing.assert_allclose(metrics[row, 1], distance[i, j], rtol=1e-12)
    assert np.isnan(metrics[:, (0, 2)]).all()


def test_duplicate_coordinates_are_ambiguous_not_merged():
    from tests.test_metrology3d_edge_support import fold, crease_settings

    points, _ = fold(np.pi / 3)
    points = np.vstack((points, points[20]))
    normals = np.asarray([[0, 0, 1], [-np.sin(np.pi / 3), 0, np.cos(np.pi / 3)]])
    _, state, partner, _ = pair_normal_points(
        points,
        np.zeros((2, 3)),
        normals,
        crease_settings(),
        options(),
        chunk_rows=2,
        cancel=lambda: None,
    )
    assert state[0] == PairStatus.NEAREST_AMBIGUOUS and partner[0] == -1
    assert state[20] == state[-1] == PairStatus.PARTNER_AMBIGUOUS


@pytest.mark.parametrize("phase", [1, 30, 100, "owner"])
def test_pair_cancel_budget_and_parent_lifetime(phase):
    scope, runtime, _, cloud, settings = prepare()
    try:
        candidates = normal_crease_candidates(
            runtime, cloud, settings, cancel=lambda: None
        )
        baseline, calls = runtime.budget.used, 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == phase or phase == "owner" and runtime.budget.used > baseline:
                raise InterruptedError("cancel-normal-pair")

        with pytest.raises(InterruptedError):
            pair_normal_candidates(runtime, candidates, options(), cancel=cancel)
        assert runtime.budget.used == baseline
        pairs = pair_normal_candidates(
            runtime, candidates, options(), cancel=lambda: None
        )
        chains = build_normal_edge_chains(runtime, pairs, cancel=lambda: None)
        runtime.storage_scope.close_resource(candidates.resource_key)
        with pytest.raises(InvalidRequestError):
            with chains.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()


def test_quality_and_space_errors_cannot_be_hidden():
    scope, runtime, _, cloud, settings = prepare()
    try:
        candidates = normal_crease_candidates(
            runtime, cloud, settings, cancel=lambda: None
        )
        pairs = pair_normal_candidates(
            runtime, candidates, options(), cancel=lambda: None
        )
        chains = build_normal_edge_chains(runtime, pairs, cancel=lambda: None)
        with pytest.raises(InvalidRequestError, match="评价面"):
            select_edge_targets(runtime, chains, targets(), cancel=lambda: None)
        result = select_edge_targets(
            runtime,
            chains,
            targets(length=3),
            evaluation=evaluation(),
            cancel=lambda: None,
        )
        assert result.reason == "insufficient_quality"
        with pytest.raises(InvalidRequestError, match="未知指标"):
            select_edge_targets(
                runtime,
                chains,
                selection(),
                evaluation=evaluation(),
                cancel=lambda: None,
            )
        runtime.policy = runtime.policy.model_copy(update={"max_working_bytes": 1024})
        with pytest.raises(InvalidRequestError, match="预算"):
            pair_normal_candidates(runtime, candidates, options(), cancel=lambda: None)
    finally:
        assert scope.close() == ()


def test_failure_observation_not_overwritten_by_success():
    """受控故障注入：同一点参与的失败窗口不能被其他成功窗口覆盖。"""
    from dataclasses import replace
    from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output

    scope, runtime, _, cloud, settings = prepare()
    try:
        candidates = normal_crease_candidates(
            runtime, cloud, settings, cancel=lambda: None
        )
        with candidates.borrow(runtime) as data:
            changed = {k: a.copy() for k, a in data.items()}
        changed["reason"][0, 0] = 1
        keys = []
        owner = own_output(runtime, changed, keys)
        candidates = replace(
            candidates,
            owner=owner,
            resource_key=keys[0],
            supported_count=candidates.supported_count - 1,
        )
        pairs = pair_normal_candidates(
            runtime, candidates, options(), cancel=lambda: None
        )
        chains = build_normal_edge_chains(runtime, pairs, cancel=lambda: None)
        result = select_edge_targets(
            runtime, chains, targets(), evaluation=evaluation(), cancel=lambda: None
        )
        assert result.reason == "pair_support_invalid"
        with pairs.borrow(runtime) as data:
            assert np.any(
                (data["reason_bits"] & (1 << PairStatus.PAIRED))
                & ((data["reason_bits"] & (1 << PairStatus.SUPPORT_INVALID)) != 0)
            )
    finally:
        assert scope.close() == ()


def test_nonmutual_observation_cannot_be_hidden_by_another_window(monkeypatch):
    """注入相互矛盾的窗口证据，不能按成功窗口优先裁决。"""
    from custom_nodes.metrology3d_nodes.shared import edge_normal_runtime as module

    scope, runtime, _, cloud, settings = prepare()
    try:
        candidates = normal_crease_candidates(
            runtime, cloud, settings, cancel=lambda: None
        )
        original = module.pair_normal_points
        calls = 0

        def inconsistent(*args, **kwargs):
            nonlocal calls
            calls += 1
            side, status, partner, metric = original(*args, **kwargs)
            if calls == 1:
                chosen = np.flatnonzero(status == PairStatus.PAIRED)
                status[chosen] = PairStatus.NOT_MUTUAL
                partner[chosen] = -1
                metric[chosen] = np.nan
            return side, status, partner, metric

        monkeypatch.setattr(module, "pair_normal_points", inconsistent)
        pairs = pair_normal_candidates(
            runtime, candidates, options(), cancel=lambda: None
        )
        with pairs.borrow(runtime) as data:
            bits = data["reason_bits"][:, 0]
            contradictory = ((bits & (1 << PairStatus.PAIRED)) != 0) & (
                (bits & (1 << PairStatus.NOT_MUTUAL)) != 0
            )
            assert contradictory.any()
            assert (data["status"][contradictory] == PairStatus.PAIRING_CONFLICT).all()
            assert (data["partners"][contradictory] == -1).all()
        chains = build_normal_edge_chains(runtime, pairs, cancel=lambda: None)
        result = select_edge_targets(
            runtime, chains, targets(), evaluation=evaluation(), cancel=lambda: None
        )
        assert result.reason == "pair_pairing_conflict"
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("stage", ["chain", "target"])
def test_downstream_cancel_after_registration_releases_new_owner(stage):
    """链/目标登记后取消仅回滚新 owner，不损坏可复用的父证据。"""
    scope, runtime, _, cloud, settings = prepare()
    try:
        candidates = normal_crease_candidates(
            runtime, cloud, settings, cancel=lambda: None
        )
        pairs = pair_normal_candidates(
            runtime, candidates, options(), cancel=lambda: None
        )
        chains = (
            build_normal_edge_chains(runtime, pairs, cancel=lambda: None)
            if stage == "target"
            else None
        )
        baseline = runtime.budget.used

        def cancel():
            if runtime.budget.used > baseline:
                raise InterruptedError("cancel-registered-edge-result")

        with pytest.raises(InterruptedError):
            if stage == "chain":
                build_normal_edge_chains(runtime, pairs, cancel=cancel)
            else:
                select_edge_targets(
                    runtime, chains, targets(), evaluation=evaluation(), cancel=cancel
                )
        assert runtime.budget.used == baseline
        with pairs.borrow(runtime) as data:
            assert np.any(data["status"] == PairStatus.PAIRED)
    finally:
        assert scope.close() == ()
