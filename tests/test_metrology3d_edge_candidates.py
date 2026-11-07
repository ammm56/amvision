"""B09 独立台阶/斜面真值、同云引用、完整支持及取消回收。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.edge3d import (
    HeightJumpCandidateSettings,
    EdgePairEvidence,
)
from backend.contracts.workflows.height_map3d import HeightMapParameters
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_height_candidates import (
    grid_pairs,
    height_jump_candidates,
    pair_evidence,
)
from custom_nodes.metrology3d_nodes.shared.height_map import cloud_to_height_map
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    publish_height_map,
)
from tests.point_cloud_support import policy
from tests.test_metrology3d_height_map import parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.integration.metrology3d.representative_recipe import boxes


def settings(**changes):
    """解析真值的显式测试尺度，不进入节点或生产默认。"""
    return HeightJumpCandidateSettings.model_validate(
        dict(
            kind="height-jump",
            adjacency=4,
            candidate_delta=0.5,
            support=dict(
                radius=1.6,
                min_points=6,
                min_tangent_ratio=0.1,
                min_normal_gap=0.1,
                max_rms=0.001,
                max_residual=0.003,
                min_joint_rms=0.01,
            ),
            support_a=boxes("side-a", [[-10, 1.49, -10, 10, -20, 20]]),
            support_b=boxes("side-b", [[1.51, 10, -10, 10, -20, 20]]),
            max_unassigned_fraction=0.2,
            min_height_axis_cosine=0.5,
            **changes,
        )
    )


def make_case(*, slope=False, gap=False, rows=32, dtype="float64"):
    """5×5 格，每格 3×3 实测点；右侧台阶为解析常数，不依赖分箱生成期望。"""
    points = np.array(
        [
            (
                column + dx,
                row + dy,
                2 * (column + dx) if slope else (2 if column >= 2 else 0),
            )
            for row in range(5)
            for column in range(5)
            if not (gap and column == 2)
            for dy in (-0.2, 0, 0.2)
            for dx in (-0.2, 0, 0.2)
        ],
        dtype=dtype,
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(
            max_working_bytes=2_000_000, max_live_array_bytes=2_000_000, chunk_rows=rows
        ),
    )
    raw = parameters().model_dump()
    raw.update(width=5, height=5)
    raw["grid"].update(row_step=1)
    grid = HeightMapParameters.model_validate(raw)
    result = cloud_to_height_map(runtime, cloud, grid, cancel=lambda: None)
    ref = publish_height_map(runtime, result)
    return scope, runtime, cloud, result, ref


@pytest.mark.parametrize("dtype", ["float32", "float64"])
@pytest.mark.parametrize("rows", [1, 17, 4096])
def test_step_all_support_and_scope(dtype, rows):
    scope, runtime, cloud, _, ref = make_case(rows=rows, dtype=dtype)
    baseline = runtime.budget.used
    try:
        result = height_jump_candidates(
            runtime, cloud, ref, settings(), cancel=lambda: None
        )
        assert result.candidate_count == result.supported_count == 5
        assert result.missing_pair_count == 0
        with result.borrow(runtime) as arrays:
            np.testing.assert_array_equal(
                arrays["cells"], [(5 * row + 1, 5 * row + 2) for row in range(5)]
            )
            for index in range(5):
                item = pair_evidence(arrays, index)
                assert item.supported and item.candidate_delta == 2
                assert min(item.side_counts) >= 6
                assert max(item.side_rms) < 1e-6
                assert item.joint_rms > 0.01
                assert item.models is not None
                for model, expected_height in zip(item.models, (0, 2)):
                    np.testing.assert_allclose(model.normal, (0, 0, 1), atol=1e-12)
                    assert model.origin[2] == expected_height
            assert all(not a.flags.writeable for a in arrays.values())
        runtime.storage_scope.close_resource(result.resource_key)
        assert runtime.budget.used == baseline
        with pytest.raises((InvalidRequestError, RuntimeError)):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def test_slope_is_not_step_and_gap_is_not_material_edge():
    for arguments, expected in ((dict(slope=True), 20), (dict(gap=True), 0)):
        scope, runtime, cloud, _, ref = make_case(**arguments)
        try:
            # 解析斜面法向 Z 分量 1/sqrt(5)，只调整本项测试方向条件。
            raw = settings().model_dump()
            raw["min_height_axis_cosine"] = 0.4
            result = height_jump_candidates(
                runtime,
                cloud,
                ref,
                HeightJumpCandidateSettings.model_validate(raw),
                cancel=lambda: None,
            )
            assert result.candidate_count == expected
            assert result.supported_count == 0
            if arguments.get("gap"):
                assert result.missing_pair_count == 10
            else:
                with result.borrow(runtime) as arrays:
                    assert all(
                        pair_evidence(arrays, i).reason
                        in {"smooth_surface", "insufficient_support"}
                        for i in range(expected)
                    )
        finally:
            assert scope.close() == ()


def test_diagonal_does_not_cross_missing_corner():
    counts = np.array([1, 0, 0, 1])
    pairs = list(grid_pairs(2, 2, 8, counts, cancel=lambda: None))
    assert (0, 3) not in pairs
    assert len(pairs) == 4


@pytest.mark.parametrize("failure_at", [1, 5, 15, 50, 100, 200])
def test_cancel_no_owned_output_leak(failure_at):
    scope, runtime, cloud, _, ref = make_case(rows=3)
    baseline, calls = runtime.budget.used, 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == failure_at:
            raise RuntimeError("test-cancel")

    try:
        with pytest.raises(RuntimeError, match="test-cancel"):
            height_jump_candidates(runtime, cloud, ref, settings(), cancel=cancel)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_wrong_cloud_and_released_parent_refused():
    scope, runtime, cloud, parent, ref = make_case()
    try:
        with pytest.raises(InvalidRequestError):
            height_jump_candidates(
                runtime,
                cloud.model_copy(update={"cloud_id": "wrong"}),
                ref,
                settings(),
                cancel=lambda: None,
            )
        result = height_jump_candidates(
            runtime, cloud, ref, settings(), cancel=lambda: None
        )
        runtime.storage_scope.close_resource(parent.resource_key)
        with pytest.raises((InvalidRequestError, RuntimeError)):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()


def test_contract_rejects_conflicting_quality_and_missing_metrics():
    raw = settings().model_dump()
    raw["support"]["min_joint_rms"] = raw["support"]["max_rms"]
    with pytest.raises(ValidationError):
        HeightJumpCandidateSettings.model_validate(raw)
    with pytest.raises(ValidationError):
        EdgePairEvidence(
            cells=(0, 1),
            candidate_delta=2,
            side_counts=(3, 3),
            window_count=6,
            unassigned_count=0,
            overlap_count=0,
            side_rms=None,
            side_max_residual=None,
            joint_rms=None,
            models=None,
            supported=True,
            reason=None,
        )


def test_budget_and_cancel_after_output_registration(monkeypatch):
    import custom_nodes.metrology3d_nodes.shared.edge_height_candidates as module

    scope, runtime, cloud, _, ref = make_case()
    baseline = runtime.budget.used
    original_policy = runtime.policy
    try:
        runtime.policy = original_policy.model_copy(update={"max_working_bytes": 4096})
        with pytest.raises(InvalidRequestError, match="工作预算"):
            height_jump_candidates(runtime, cloud, ref, settings(), cancel=lambda: None)
        assert runtime.budget.used == baseline
        runtime.policy = original_policy
        captured = []
        original = module.own_output

        def capture(*args):
            owner = original(*args)
            captured.append(owner)
            return owner

        def cancel():
            if captured:
                raise InterruptedError("after-owned")

        monkeypatch.setattr(module, "own_output", capture)
        with pytest.raises(InterruptedError):
            height_jump_candidates(runtime, cloud, ref, settings(), cancel=cancel)
        assert captured[0].closed and runtime.budget.used == baseline
    finally:
        scope.close()


def test_subcell_shift_exposes_support_split_not_quality_relaxation():
    """真台阶落在格内部时，格面对半不等于物理两侧；保留混面失败而非假通过。"""
    from custom_nodes.metrology3d_nodes.shared.edge_support import verify_edge_support

    rows = np.array(
        [
            (x, y, 0 if x < 1 else 2)
            for x in np.linspace(0.1, 1.9, 19)
            for y in np.linspace(-1, 1, 21)
        ]
    )
    candidate_center = np.array([0.5, 0])
    left = rows[:, 0] < candidate_center[0]
    *_, reason = verify_edge_support(
        rows, np.column_stack((left, ~left)), settings(), 32, lambda: None
    )
    assert reason in {"height_direction_ambiguous", "side_quality_failed"}
    # 同一批点只按独立已知的实物分隔位置组织支持，原质量条件可以通过。
    left = rows[:, 0] < 1
    *_, true_reason = verify_edge_support(
        rows, np.column_stack((left, ~left)), settings(), 32, lambda: None
    )
    assert true_reason is None


@pytest.mark.parametrize("case", ["overlap", "unassigned", "wrong-frame"])
def test_explicit_roi_rejects_ambiguous_and_wrong_identity(case):
    scope, runtime, cloud, _, ref = make_case()
    raw = settings().model_dump()
    try:
        if case == "overlap":
            raw["support_b"] = raw["support_a"]
        elif case == "unassigned":
            raw["support_a"] = boxes("far-a", [[50, 51, 50, 51, 0, 1]]).model_dump()
            raw["support_b"] = boxes("far-b", [[52, 53, 50, 51, 0, 1]]).model_dump()
        else:
            for roi in raw["support_b"]["rois"]:
                roi["frame_id"] = "wrong"
            with pytest.raises(InvalidRequestError, match="坐标"):
                height_jump_candidates(
                    runtime,
                    cloud,
                    ref,
                    HeightJumpCandidateSettings.model_validate(raw),
                    cancel=lambda: None,
                )
            return
        result = height_jump_candidates(
            runtime,
            cloud,
            ref,
            HeightJumpCandidateSettings.model_validate(raw),
            cancel=lambda: None,
        )
        assert result.supported_count == 0
        with result.borrow(runtime) as arrays:
            expected = "support_overlap" if case == "overlap" else "unassigned_support"
            assert all(
                pair_evidence(arrays, i).reason == expected
                for i in range(result.candidate_count)
            )
    finally:
        scope.close()


def test_subset_keeps_original_source_rows():
    from tests.test_point_cloud_runtime import method, own

    scope, runtime, cloud, parent, _ = make_case()
    try:
        child = runtime.register_subset(
            parent=cloud,
            method=method(),
            indices=own(
                runtime,
                {
                    "indices": np.arange(0, cloud.point_count, 2, dtype="u4").reshape(
                        -1, 1
                    )
                },
            ),
            cancel=lambda: None,
        )
        grid = HeightMapParameters.model_validate_json(parent.parameters_json)
        height = cloud_to_height_map(runtime, child, grid, cancel=lambda: None)
        ref = publish_height_map(runtime, height)
        result = height_jump_candidates(
            runtime, child, ref, settings(), cancel=lambda: None
        )
        assert result.supported_count == 5
        with height.borrow(runtime) as arrays:
            np.testing.assert_array_equal(
                arrays["source_rows"][:, 0],
                2 * arrays["input_rows"][:, 0],
            )
        assert runtime.source_point_count(child) == cloud.point_count
    finally:
        scope.close()


@pytest.mark.parametrize("chunk_rows", [7, 4096])
def test_rotated_grid_and_source_roi_keep_same_support(chunk_rows):
    """独立旋转完整输入/ROI/格轴，源 ROI 不得在投影后的局部坐标中求值。"""
    scope, runtime, cloud, height, ref = make_case(rows=chunk_rows)
    rotated_scope = None
    try:
        baseline = height_jump_candidates(
            runtime, cloud, ref, settings(), cancel=lambda: None
        )
        with baseline.borrow(runtime) as arrays:
            expected = {key: value.copy() for key, value in arrays.items()}
        with runtime.borrow(cloud) as view:
            original = np.concatenate(
                [
                    view.chunk(start, min(start + chunk_rows, cloud.point_count))[
                        "positions"
                    ]
                    for start in range(0, cloud.point_count, chunk_rows)
                ]
            )
        angle = 0.37
        c, s = np.cos(angle), np.sin(angle)
        rotation = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        translation = np.array([1030.0, -71.0, 26.0])
        transformed = original @ rotation.T + translation
        rotated_scope, transformed_runtime, transformed_cloud = make_cloud(
            unit="mm", coordinates=transformed, runtime_policy=runtime.policy
        )
        grid_raw = HeightMapParameters.model_validate_json(
            height.parameters_json
        ).model_dump()
        grid_raw["grid"].update(
            origin=translation,
            column_direction=rotation[:, 0],
            row_direction=rotation[:, 1],
            height_direction=rotation[:, 2],
        )
        shifted_height = cloud_to_height_map(
            transformed_runtime,
            transformed_cloud,
            HeightMapParameters.model_validate(grid_raw),
            cancel=lambda: None,
        )
        raw = settings().model_dump()
        for name in ("support_a", "support_b"):
            for roi in raw[name]["rois"]:
                if roi["kind"] == "box":
                    geometry = roi["geometry"]
                    geometry["center"] = rotation @ geometry["center"] + translation
                    geometry["rotation"] = rotation
        shifted = height_jump_candidates(
            transformed_runtime,
            transformed_cloud,
            publish_height_map(transformed_runtime, shifted_height),
            HeightJumpCandidateSettings.model_validate(raw),
            cancel=lambda: None,
        )
        with shifted.borrow(transformed_runtime) as arrays:
            for key in ("cells", "counts", "window_counts", "reason"):
                np.testing.assert_array_equal(arrays[key], expected[key])
            for key in ("delta", "rms", "maximum", "model_origins", "model_normals"):
                np.testing.assert_allclose(
                    arrays[key], expected[key], atol=1e-11, rtol=0
                )
    finally:
        if rotated_scope is not None:
            assert rotated_scope.close() == ()
            assert transformed_runtime.budget.used == 0
        assert scope.close() == ()


def test_candidate_models_are_same_run_readonly_and_required():
    """后续配对必须借用当次模型；证据不能删模型后仍自称支持通过。"""
    scope, runtime, cloud, _, ref = make_case()
    try:
        result = height_jump_candidates(
            runtime, cloud, ref, settings(), cancel=lambda: None
        )
        with result.borrow(runtime) as arrays:
            assert arrays["model_origins"].shape == (5, 6)
            assert arrays["model_normals"].shape == (5, 6)
            assert not arrays["model_origins"].flags.writeable
            assert not arrays["model_normals"].flags.writeable
            document = pair_evidence(arrays, 0).model_dump()
            document["models"] = None
            with pytest.raises(ValidationError, match="缺少拟面证据"):
                EdgePairEvidence.model_validate(document)
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def test_support_union_does_not_duplicate_contributions():
    """同侧多个重叠 ROI 是布尔并集，不得增加点权重或改变拟面。"""
    from copy import deepcopy

    scope, runtime, cloud, _, ref = make_case()
    try:
        original = height_jump_candidates(
            runtime, cloud, ref, settings(), cancel=lambda: None
        )
        raw = settings().model_dump()
        for name in ("support_a", "support_b"):
            rois = list(raw[name]["rois"])
            duplicate = deepcopy(rois[0])
            duplicate["roi_id"] += "-duplicate"
            rois[-1]["geometry"]["roi_ids"] = (
                *rois[-1]["geometry"]["roi_ids"],
                duplicate["roi_id"],
            )
            rois.append(duplicate)
            raw[name]["rois"] = rois
        combined = height_jump_candidates(
            runtime,
            cloud,
            ref,
            HeightJumpCandidateSettings.model_validate(raw),
            cancel=lambda: None,
        )
        with original.borrow(runtime) as a, combined.borrow(runtime) as b:
            for key in a:
                np.testing.assert_array_equal(a[key], b[key])
    finally:
        assert scope.close() == ()
