"""B09 实测点对的独立真值、同次来源、诊断与所有权。"""

import numpy as np
import pytest

from backend.contracts.workflows.edge3d import HeightJumpPairingSettings
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_pairing import PairStatus, pair_points
from custom_nodes.metrology3d_nodes.shared.edge_pair_runtime import (
    pair_height_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_height_candidates import (
    height_jump_candidates,
)
from tests.test_metrology3d_edge_candidates import make_case, settings


def pairing():
    """只用于解析台阶的测试尺度。"""
    return HeightJumpPairingSettings(max_planar_gap=0.65, tie_tolerance=1e-10)


@pytest.mark.parametrize("chunk", [1, 7, 4096])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_real_pairs_keep_all_records_and_original_identity(chunk, dtype):
    scope, runtime, cloud, _, ref = make_case(rows=chunk, dtype=dtype)
    baseline = runtime.budget.used
    try:
        candidates = height_jump_candidates(
            runtime, cloud, ref, settings(), cancel=lambda: None
        )
        result = pair_height_candidates(
            runtime, cloud, candidates, pairing(), cancel=lambda: None
        )
        assert result.pair_count == 15
        with result.borrow(runtime) as arrays:
            # 五格对，每对两格18个贡献记录；没有只留下30个成功点。
            assert len(arrays["status"]) == 90
            np.testing.assert_array_equal(arrays["offsets"][:, 0], np.arange(6) * 18)
            np.testing.assert_array_equal(arrays["input_rows"], arrays["source_rows"])
            assert all(not a.flags.writeable for a in arrays.values())
            selected = np.flatnonzero(arrays["status"][:, 0] == PairStatus.PAIRED)
            assert len(selected) == 30
            for row in selected:
                other = int(arrays["partners"][row, 0])
                assert arrays["partners"][other, 0] == row
                assert arrays["sides"][other, 0] != arrays["sides"][row, 0]
                x, y, z = arrays["positions"][row]
                xx, yy, zz = arrays["positions"][other]
                np.testing.assert_allclose(sorted((x, xx)), (1.2, 1.8), atol=1e-6)
                assert y == yy and abs(z - zz) == 2
                np.testing.assert_allclose(
                    arrays["metrics"][row], (0.6, np.hypot(0.6, 2), zz - z), atol=1e-6
                )
        runtime.storage_scope.close_resource(result.resource_key)
        runtime.storage_scope.close_resource(candidates.resource_key)
        assert runtime.budget.used == baseline
        with pytest.raises(InvalidRequestError):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def direct(points, *, origins=None, normals=None, parameters=None):
    return pair_points(
        np.asarray(points, dtype=float),
        np.array([[0, 0, 0], [0, 0, 2]]) if origins is None else origins,
        np.array([[0, 0, 1], [0, 0, 1]]) if normals is None else normals,
        settings(),
        parameters or pairing(),
        chunk_rows=2,
        cancel=lambda: None,
    )


def test_equal_distance_is_not_broken_by_record_order():
    points = np.array([[0, 0, 0], [0.3, 0.4, 2], [0.3, -0.4, 2]])
    for order in ([0, 1, 2], [2, 0, 1]):
        sides, state, partner, _ = direct(points[order])
        assert state[sides == 0].tolist() == [PairStatus.NEAREST_AMBIGUOUS]
        assert set(state[sides == 1]) == {PairStatus.PARTNER_AMBIGUOUS}
        assert (partner == -1).all()


def test_duplicate_records_are_not_silently_merged():
    _, state, partner, _ = direct([[0, 0, 0], [0.5, 0, 2], [0.5, 0, 2]])
    assert state[0] == PairStatus.NEAREST_AMBIGUOUS
    assert (partner == -1).all()


def test_missing_assignment_and_planar_gap_are_explicit():
    _, state, partner, metrics = direct([[0, 0, 0], [1, 0, 2], [0, 1, 1]])
    assert state.tolist() == [
        PairStatus.GAP_EXCEEDED,
        PairStatus.GAP_EXCEEDED,
        PairStatus.UNASSIGNED,
    ]
    assert (partner == -1).all() and np.isnan(metrics).all()
    _, state, _, _ = direct([[0, 0, 0], [0, 1, 0]])
    assert set(state) == {PairStatus.OTHER_SIDE_MISSING}
    _, state, _, _ = direct([[0, 0, 0]], origins=np.zeros((2, 3)))
    assert state.tolist() == [PairStatus.SURFACE_AMBIGUOUS]


def test_planar_distance_is_not_three_dimensional_distance():
    _, state, _, metrics = direct([[0, 0, 0], [0.5, 0, 2]])
    assert set(state) == {PairStatus.PAIRED}
    assert metrics[0, 0] == 0.5 and metrics[0, 1] > 2
    assert metrics[0, 2] == 2 and metrics[1, 2] == -2


def test_fold_with_no_common_position_jump_is_not_step():
    # 两个锐折平面在 x=0 接合；实测点高度不同不等于存在高度不连续。
    normals = np.array([[0, 0, 1], [-2, 0, 1]]) / np.array([[1], [np.sqrt(5)]])
    _, state, partner, _ = direct(
        [[-0.3, 0, 0], [0.3, 0, 0.6]],
        origins=np.zeros((2, 3)),
        normals=normals,
    )
    assert set(state) == {PairStatus.NOT_HEIGHT_JUMP}
    assert (partner == -1).all()


@pytest.mark.parametrize("failure_at", [1, 5, 15, 40, 100])
def test_pair_cancel_and_budget_do_not_leak(failure_at):
    scope, runtime, cloud, _, ref = make_case(rows=2)
    try:
        candidates = height_jump_candidates(
            runtime, cloud, ref, settings(), cancel=lambda: None
        )
        baseline = runtime.budget.used
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == failure_at:
                raise InterruptedError("pair-cancel")

        with pytest.raises(InterruptedError):
            pair_height_candidates(runtime, cloud, candidates, pairing(), cancel=cancel)
        assert runtime.budget.used == baseline
        runtime.policy = runtime.policy.model_copy(update={"max_working_bytes": 1024})
        with pytest.raises(InvalidRequestError, match="预算"):
            pair_height_candidates(
                runtime, cloud, candidates, pairing(), cancel=lambda: None
            )
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_wrong_cloud_and_parent_release_rejected():
    scope, runtime, cloud, _, ref = make_case()
    try:
        candidates = height_jump_candidates(
            runtime, cloud, ref, settings(), cancel=lambda: None
        )
        with pytest.raises(InvalidRequestError):
            pair_height_candidates(
                runtime,
                cloud.model_copy(update={"cloud_id": "other"}),
                candidates,
                pairing(),
                cancel=lambda: None,
            )
        result = pair_height_candidates(
            runtime, cloud, candidates, pairing(), cancel=lambda: None
        )
        runtime.storage_scope.close_resource(candidates.resource_key)
        with pytest.raises(InvalidRequestError):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()


def test_mutual_pairs_match_full_distance_truth_under_permutation():
    rng = np.random.default_rng(943)
    left = np.column_stack(
        (rng.uniform(-0.3, 0, 27), rng.uniform(0, 4, 27), np.zeros(27))
    )
    right = np.column_stack(
        (rng.uniform(0.2, 0.4, 31), rng.uniform(0, 4, 31), np.full(31, 2))
    )
    distance = np.sqrt(((left[:, None, :2] - right[None, :, :2]) ** 2).sum(axis=2))
    a, b = distance.argmin(axis=1), distance.argmin(axis=0)
    expected = {
        (i, int(j) + len(left))
        for i, j in enumerate(a)
        if b[j] == i and distance[i, j] <= pairing().max_planar_gap
    }
    original = np.vstack((left, right))
    for _ in range(3):
        permutation = rng.permutation(len(original))
        sides, state, partners, _ = direct(original[permutation])
        actual = {
            (int(permutation[row]), int(permutation[partners[row]]))
            for row in np.flatnonzero((sides == 0) & (state == PairStatus.PAIRED))
        }
        assert actual == expected
