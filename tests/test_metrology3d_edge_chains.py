"""B09 连续实测段：不跨空格，不把歧义和未解释支持隐藏在成功段中。"""

import numpy as np
import pytest

from backend.contracts.workflows.edge3d import EdgeChainSettings
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_chains import _build, build_edge_chains
from custom_nodes.metrology3d_nodes.shared.edge_height_candidates import (
    height_jump_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_pair_runtime import (
    pair_height_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_pairing import PairStatus
from tests.test_metrology3d_edge_candidates import make_case, settings
from tests.test_metrology3d_edge_pairing import pairing


def chain_settings(side="high", distance=0.7):
    """解析点间距为 0.2/0.6，仅定义本测试的连接尺度。"""
    return EdgeChainSettings(side=side, max_link_distance=distance, max_turn_angle=0.01)


def prepare(**kwargs):
    """创建真实运行所有权，不用假引用代替父云/格/配对。"""
    scope, runtime, cloud, result, ref = make_case(**kwargs)
    candidates = height_jump_candidates(
        runtime, cloud, ref, settings(), cancel=lambda: None
    )
    pairs = pair_height_candidates(
        runtime, cloud, candidates, pairing(), cancel=lambda: None
    )
    return scope, runtime, result, ref, candidates, pairs


@pytest.mark.parametrize("side,height,x", [("high", 2, 1.8), ("low", 0, 1.2)])
@pytest.mark.parametrize(
    "chunk,dtype", [(1, "float32"), (7, "float64"), (4096, "float64")]
)
@pytest.mark.parametrize("distance,segments", [(0.7, 1), (0.5, 5)])
def test_continuous_source_chain_and_explicit_gap(
    side, height, x, chunk, dtype, distance, segments
):
    scope, runtime, _, _, _, pairs = prepare(rows=chunk, dtype=dtype)
    baseline = runtime.budget.used
    try:
        result = build_edge_chains(
            runtime, pairs, chain_settings(side, distance), cancel=lambda: None
        )
        assert result.reason is None
        with result.borrow(runtime) as data:
            assert len(data["positions"]) == 15
            assert len(data["closed"]) == segments
            assert not data["closed"].any() and not len(data["isolated"])
            np.testing.assert_allclose(data["positions"][:, 0], x, atol=1e-6)
            np.testing.assert_array_equal(data["positions"][:, 2], height)
            np.testing.assert_allclose(
                np.sort(data["positions"][:, 1]),
                [r + d for r in range(5) for d in (-0.2, 0, 0.2)],
                atol=1e-6,
            )
            np.testing.assert_array_equal(data["input_rows"], data["source_rows"])
            assert len(np.unique(data["input_rows"])) == 15
            assert all(not a.flags.writeable for a in data.values())
        runtime.storage_scope.close_resource(result.resource_key)
        assert runtime.budget.used == baseline
        with pytest.raises(InvalidRequestError):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def copied(runtime, result):
    """只供纯内核故障测试，不伪造运行时登记。"""
    with result.borrow(runtime) as data:
        return {name: array.copy() for name, array in data.items()}


def test_empty_corner_and_unexplained_endpoint_do_not_connect():
    scope, runtime, height, ref, candidates, pairs = prepare()
    try:
        data, candidate_data = copied(runtime, pairs), copied(runtime, candidates)
        counts = copied(runtime, height)["counts"][:, 0]

        def build():
            return _build(
                data,
                candidate_data,
                ref.evidence.parameters,
                counts,
                chain_settings(),
                pairing().tie_tolerance,
                cancel=lambda: None,
            )

        assert len(build()[3]) == 14
        counts[7] = 0
        assert len(build()[3]) == 12
        counts[7] = 9
        # 第一格对尾端之外有未解释记录，不能跳过它连到第二格对。
        selected = int(data["offsets"][1, 0]) - 1
        data["status"][selected, 0] = PairStatus.UNASSIGNED
        data["positions"][selected, 1] = 0.4
        assert len(build()[3]) == 13
    finally:
        assert scope.close() == ()


def test_failed_candidate_does_not_connect_across_its_cell():
    scope, runtime, height, ref, candidates, pairs = prepare()
    try:
        data = copied(runtime, pairs)
        start, stop = data["offsets"][2:4, 0].astype(int)
        data["status"][start:stop] = PairStatus.SUPPORT_INVALID
        rows, _, _, edges, reason = _build(
            data,
            copied(runtime, candidates),
            ref.evidence.parameters,
            copied(runtime, height)["counts"][:, 0],
            chain_settings(distance=10),
            pairing().tie_tolerance,
            cancel=lambda: None,
        )
        assert reason is None and len(rows) == 12 and len(edges) == 10
    finally:
        assert scope.close() == ()


def test_isolated_points_remain_diagnostic():
    scope, runtime, _, _, _, pairs = prepare()
    try:
        result = build_edge_chains(
            runtime, pairs, chain_settings(distance=0.1), cancel=lambda: None
        )
        assert result.reason == "no_boundary"
        with result.borrow(runtime) as data:
            assert len(data["isolated"]) == len(data["positions"]) == 15
            assert len(data["segment_rows"]) == 0
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("failure_at", [1, 3, 10, 30, 60])
def test_chain_cancel_budget_and_parent_release(failure_at):
    scope, runtime, _, _, _, pairs = prepare()
    baseline = runtime.budget.used
    try:
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == failure_at:
                raise InterruptedError("chain-cancel")

        with pytest.raises(InterruptedError):
            build_edge_chains(runtime, pairs, chain_settings(), cancel=cancel)
        assert runtime.budget.used == baseline
        result = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        runtime.storage_scope.close_resource(pairs.resource_key)
        with pytest.raises(InvalidRequestError):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def test_chain_budget_rejects_before_output():
    scope, runtime, _, _, _, pairs = prepare()
    baseline = runtime.budget.used
    try:
        runtime.policy = runtime.policy.model_copy(update={"max_working_bytes": 1024})
        with pytest.raises(InvalidRequestError, match="预算"):
            build_edge_chains(runtime, pairs, chain_settings(), cancel=lambda: None)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_anisotropic_grid_order_uses_physical_direction():
    scope, runtime, height, ref, candidates, pairs = prepare()
    try:
        data = copied(runtime, pairs)
        data["offsets"] = np.array([[0], [4]], dtype="<u8")
        data["status"][:4, 0] = PairStatus.PAIRED
        data["sides"][:4, 0] = (0, 1, 0, 1)
        data["partners"][:4, 0] = (1, 0, 3, 2)
        data["metrics"][:4, 2] = (2, -2, 2, -2)
        data["positions"][:4] = ((-0.1, 0, 0), (0, 0, 2), (0.9, 1, 0), (1, 1, 2))
        candidate = {"cells": np.array([[0, 6]])}
        parameters = ref.evidence.parameters.model_copy(
            update={
                "grid": ref.evidence.parameters.grid.model_copy(
                    update={"column_step": 2}
                )
            }
        )
        rows, _, _, edges, reason = _build(
            data,
            candidate,
            parameters,
            copied(runtime, height)["counts"][:, 0],
            chain_settings(distance=2),
            pairing().tie_tolerance,
            cancel=lambda: None,
        )
        assert reason is None and len(rows) == 2 and len(edges) == 1
    finally:
        assert scope.close() == ()


def test_equal_along_position_is_ambiguous_not_source_order():
    scope, runtime, height, ref, candidates, pairs = prepare()
    try:
        data = copied(runtime, pairs)
        chosen = np.flatnonzero(
            (data["status"][:, 0] == PairStatus.PAIRED) & (data["sides"][:, 0] == 1)
        )
        data["positions"][chosen[1], 1] = data["positions"][chosen[0], 1]
        *_, reason = _build(
            data,
            copied(runtime, candidates),
            ref.evidence.parameters,
            copied(runtime, height)["counts"][:, 0],
            chain_settings(),
            pairing().tie_tolerance,
            cancel=lambda: None,
        )
        assert reason == "edge_order_ambiguous"
    finally:
        assert scope.close() == ()


def test_eight_adjacency_repeated_observations_are_not_branches():
    scope, runtime, cloud, _, ref = make_case()
    try:
        raw = settings().model_dump()
        raw["adjacency"] = 8
        candidates = height_jump_candidates(
            runtime,
            cloud,
            ref,
            type(settings()).model_validate(raw),
            cancel=lambda: None,
        )
        pairs = pair_height_candidates(
            runtime, cloud, candidates, pairing(), cancel=lambda: None
        )
        result = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        assert result.reason is None
        with result.borrow(runtime) as data:
            assert len(data["positions"]) == 15
            assert len(data["closed"]) == 1
    finally:
        assert scope.close() == ()


def test_equal_endpoint_links_remain_ambiguous():
    scope, runtime, height, ref, _, pairs = prepare()
    try:
        data = copied(runtime, pairs)
        data["offsets"] = np.array([[0], [4], [8]], dtype="<u8")
        data["status"][:8, 0] = PairStatus.PAIRED
        data["sides"][:8, 0] = (0, 1, 0, 1) * 2
        data["partners"][:8, 0] = (1, 0, 3, 2, 5, 4, 7, 6)
        data["metrics"][:8, 2] = (2, -2) * 4
        data["positions"][:8] = (
            (-1, -0.1, 0),
            (-1, 0, 2),
            (1, -0.1, 0),
            (1, 0, 2),
            (-1, 0.9, 0),
            (-1, 1, 2),
            (1, 0.9, 0),
            (1, 1, 2),
        )
        *_, reason = _build(
            data,
            {"cells": np.array([[0, 5], [1, 6]])},
            ref.evidence.parameters,
            copied(runtime, height)["counts"][:, 0],
            chain_settings(distance=3),
            pairing().tie_tolerance,
            cancel=lambda: None,
        )
        assert reason == "edge_link_ambiguous"
    finally:
        assert scope.close() == ()


def test_turn_failure_keeps_evidence_but_no_consumable_segment(monkeypatch):
    from custom_nodes.metrology3d_nodes.shared import edge_chains

    scope, runtime, _, _, _, pairs = prepare()
    original = edge_chains._build

    def bent(*args, **kwargs):
        rows, other, points, edges, reason = original(*args, **kwargs)
        points[7, 0] += 0.1
        return rows, other, points, edges, reason

    monkeypatch.setattr(edge_chains, "_build", bent)
    try:
        result = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        assert result.reason == "edge_turn_exceeded"
        with result.borrow(runtime) as data:
            assert len(data["positions"]) == 15 and len(data["edges"]) == 14
            assert not len(data["closed"]) and not len(data["segment_rows"])
    finally:
        assert scope.close() == ()


def test_after_registration_cancel_closes_chain_owner():
    scope, runtime, _, _, _, pairs = prepare()
    baseline = runtime.budget.used

    def cancel():
        if runtime.budget.used > baseline:
            raise InterruptedError("after-owner")

    try:
        with pytest.raises(InterruptedError, match="after-owner"):
            build_edge_chains(runtime, pairs, chain_settings(), cancel=cancel)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()
