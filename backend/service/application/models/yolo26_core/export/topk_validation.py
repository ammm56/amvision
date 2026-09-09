"""YOLO26 processed TopK 的候选、完整行及两阶段选择语义校验。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.model_artifact_runtime_smoke import (
    summarize_runtime_output_consistency,
)


def validate_topk_outputs(
    *,
    source_candidates: Any,
    target_candidates: Any,
    source_outputs: list[Any],
    target_outputs: list[Any],
    class_count: int,
    build_precision: str,
    np_module: Any,
    source_observed_outputs: list[Any] | None = None,
    target_observed_outputs: list[Any] | None = None,
) -> dict[str, object]:
    """分别校验观测执行的选择、候选数值与正式输出的完整交接。

    observed_outputs 必须与对应 candidates 来自同一次观测执行；未提供时，
    outputs 自身就是该执行的结果。重新编译的观测图不能冒充正式产物。
    """
    np = np_module
    source_observed = (
        source_outputs if source_observed_outputs is None else source_observed_outputs
    )
    target_observed = (
        target_outputs if target_observed_outputs is None else target_observed_outputs
    )
    raw = summarize_runtime_output_consistency(
        source_outputs=[source_candidates, *source_observed[1:]],
        target_outputs=[target_candidates, *target_observed[1:]],
        build_precision=build_precision,
        np_module=np,
    )
    row = summarize_runtime_output_consistency(
        source_outputs=source_outputs,
        target_outputs=target_outputs,
        build_precision=build_precision,
        np_module=np,
    )
    # proto 等固定顺序输出仍直接比较正式产物，不能累加两端观测交接的容差。
    public_auxiliary = (
        summarize_runtime_output_consistency(
            source_outputs=source_outputs[1:],
            target_outputs=target_outputs[1:],
            build_precision=build_precision,
            np_module=np,
        )
        if len(source_outputs) > 1
        else None
    )
    selection: list[dict[str, object]] = []
    score_error = (
        float(
            np.max(
                np.abs(
                    np.asarray(source_candidates)[:, :, 4 : 4 + class_count]
                    - np.asarray(target_candidates)[:, :, 4 : 4 + class_count]
                )
            )
        )
        if raw["finite"]
        else 0.0
    )
    for candidates, outputs in (
        (source_candidates, source_observed),
        (target_candidates, target_observed),
    ):
        selection.append(
            _validate_selection(
                candidates=np.asarray(candidates),
                processed=np.asarray(outputs[0]),
                class_count=class_count,
                np=np,
            )
        )
    bridges = [
        _validate_public_observation(
            candidates=np.asarray(candidates),
            observed=observed,
            public=public,
            class_count=class_count,
            build_precision=build_precision,
            np=np,
        )
        for candidates, observed, public in (
            (source_candidates, source_observed, source_outputs),
            (target_candidates, target_observed, target_outputs),
        )
    ]
    passed = (
        raw["passed"] is True
        and (public_auxiliary is None or public_auxiliary["passed"] is True)
        and all(item["passed"] for item in selection)
        and all(item["passed"] for item in bridges)
    )
    return {
        "stage": "validate-onnx",
        "strategy": "yolo26-topk-v3",
        "passed": passed,
        "accepted": passed,
        "allclose": passed,
        "finite": raw["finite"] and row["finite"],
        "max_abs_diff": raw["max_abs_diff"],
        "mean_abs_diff": raw["mean_abs_diff"],
        "raw_row_allclose": row["allclose"],
        "row_max_abs_diff": row["max_abs_diff"],
        "candidate_validation": raw,
        "selection_validation": selection,
        "public_observation_validation": bridges,
        "public_auxiliary_validation": public_auxiliary,
        "candidate_score_max_abs_diff": score_error,
        "output_count": len(source_outputs),
    }


def _validate_selection(
    *,
    candidates: Any,
    processed: Any,
    class_count: int,
    np: Any,
) -> dict[str, object]:
    """构造可核验的 stage1 候选集合，并检查完整输出及 stage2 阈值。"""

    def fail(reason: str) -> dict[str, object]:
        """返回明确失败原因，由调用方决定终止转换。"""
        return {"passed": False, "reason": reason}

    if candidates.ndim != 3 or processed.ndim != 3 or class_count < 1:
        return fail("invalid rank or class count")
    batch, anchors, channels = candidates.shape
    if anchors < 1 or channels < 4 + class_count:
        return fail("invalid candidate shape")
    k = min(300, anchors)
    if processed.shape != (batch, k, channels - class_count + 2):
        return fail("invalid processed shape")
    if not np.isfinite(candidates).all() or not np.isfinite(processed).all():
        return fail("non-finite value")
    for candidate, rows in zip(candidates, processed, strict=True):
        scores = candidate[:, 4 : 4 + class_count]
        if np.any(scores < 0) or np.any(scores > 1):
            return fail("invalid candidate probability")
        # 同次执行的 Split/Gather/Concat 仅复制元素，不产生模型计算误差。
        # 跨后端误差只能用于候选数值比较，不能放宽本后端的选择规则。
        score_epsilon = 0.0
        if np.any(rows[:, 4] < 0) or np.any(rows[:, 4] > 1):
            return fail("invalid probability")
        if np.any(rows[1:, 4] > rows[:-1, 4] + score_epsilon):
            return fail("unsorted selected scores")
        matches: list[list[int]] = []
        for row in rows:
            category = int(row[5])
            if row[5] != category or not 0 <= category < class_count:
                return fail("invalid class id")
            score_match = scores[:, category] == row[4]
            geometry_match = (candidate[:, :4] == row[:4]).all(axis=1)
            extra_match = (candidate[:, 4 + class_count :] == row[6:]).all(axis=1)
            ids = np.flatnonzero(score_match & geometry_match & extra_match)
            if not len(ids):
                return fail("processed row does not match a complete candidate")
            matches.append([int(anchor) * class_count + category for anchor in ids])
        # 二分匹配防止两个输出重复占用同一个 anchor/class；相同 anchor 不同 class 合法。
        owners: dict[int, int] = {}

        def assign(row_index: int, visited: set[int]) -> bool:
            """为当前输出寻找未占用或可重新分配的候选标识。"""
            for key in matches[row_index]:
                if key in visited:
                    continue
                visited.add(key)
                if key not in owners or assign(owners[key], visited):
                    owners[key] = row_index
                    return True
            return False

        if any(not assign(index, set()) for index in range(k)):
            return fail("duplicate anchor/class selection")
        selected_pairs = set(owners)
        selected_anchors = {key // class_count for key in selected_pairs}
        anchor_scores = scores.max(axis=1)
        # 用完整输出涉及的 anchor 加上剩余最高分 anchor 构造 stage1 见证。
        # 若这种最优补全集合仍不合法，则不存在能产生该结果的两阶段 TopK。
        first = set(selected_anchors)
        floor = float(rows[:, 4].min())
        for index in np.argsort(-anchor_scores, kind="stable"):
            if len(first) == k:
                break
            # 未出现在 stage2 的补充 anchor 不能带入高于最终边界的分数。
            if anchor_scores[index] <= floor + score_epsilon:
                first.add(int(index))
        if len(first) != k:
            return fail("stage1 cannot be completed without missing a higher score")
        first_ids = np.array(sorted(first), dtype=np.int64)
        outside = np.ones(anchors, dtype=bool)
        outside[first_ids] = False
        if (
            outside.any()
            and anchor_scores[outside].max()
            > anchor_scores[first_ids].min() + score_epsilon
        ):
            return fail("stage1 omitted a higher score anchor")
        for anchor in first:
            for category in np.flatnonzero(scores[anchor] > floor + score_epsilon):
                if anchor * class_count + int(category) not in selected_pairs:
                    return fail("stage2 omitted a higher score class")
    return {"passed": True, "selected_rows_per_batch": k, "witness": "two-stage-topk"}


def _validate_public_observation(
    *,
    candidates: Any,
    observed: list[Any],
    public: list[Any],
    class_count: int,
    build_precision: str,
    np: Any,
) -> dict[str, object]:
    """验证正式结果，不能只验证重新编译的观测产物。

    正式结果可直接满足观测候选的精确选择（允许真正同分的不同集合），
    或与观测结果逐实例完整匹配。后一种仅证明输出数值等价，不声称读取了
    正式 engine 的内部候选；无法对应的近同分集合报告不可验证并拒绝发布。
    """
    if not observed or len(observed) != len(public):
        return {"passed": False, "reason": "public/observation output count mismatch"}
    if any(
        np.asarray(a).shape != np.asarray(b).shape
        for a, b in zip(observed, public, strict=True)
    ):
        return {"passed": False, "reason": "public/observation output shape mismatch"}
    if not all(np.isfinite(value).all() for value in (*observed, *public)):
        return {"passed": False, "reason": "non-finite public/observation output"}
    if (
        observed[1:]
        and not summarize_runtime_output_consistency(
            source_outputs=observed[1:],
            target_outputs=public[1:],
            build_precision=build_precision,
            np_module=np,
        )["passed"]
    ):
        return {
            "passed": False,
            "reason": "public/observation auxiliary output mismatch",
        }
    exact = _validate_selection(
        candidates=candidates,
        processed=np.asarray(public[0]),
        class_count=class_count,
        np=np,
    )
    if exact["passed"]:
        return {"passed": True, "method": "exact-candidate-selection"}
    rtol, atol = (1e-3, 1e-4) if build_precision == "fp32" else (2e-2, 5e-3)
    for reference, rows in zip(observed[0], public[0], strict=True):
        if np.any(rows[:, 4] < 0) or np.any(rows[:, 4] > 1):
            return {"passed": False, "reason": "invalid public probability"}
        if np.any(rows[1:, 4] > rows[:-1, 4]):
            return {"passed": False, "reason": "unsorted public scores"}
        matches = [
            np.flatnonzero(
                (reference[:, 5] == row[5])
                & np.isclose(reference, row, rtol=rtol, atol=atol).all(axis=1)
            ).tolist()
            for row in rows
        ]
        owners: dict[int, int] = {}

        def assign(index: int, visited: set[int]) -> bool:
            """为正式实例匹配唯一的完整观测实例，不允许重复占用。"""
            for key in matches[index]:
                if key in visited:
                    continue
                visited.add(key)
                if key not in owners or assign(owners[key], visited):
                    owners[key] = index
                    return True
            return False

        if any(not assign(index, set()) for index in range(len(rows))):
            return {
                "passed": False,
                "reason": "public/observation correspondence unverified",
            }
    return {"passed": True, "method": "complete-output-equivalence"}
