"""YOLO 主线候选结果裁剪辅助。"""

from __future__ import annotations

from typing import Any


def select_top_scoring_candidate_indices(
    *,
    np_module: Any,
    scores: Any,
    max_candidate_count: int,
) -> Any | None:
    """按 score 选择进入重型后处理的最高分候选索引。

    OBB rotated NMS 这类后处理在 Python 路径里代价较高。未训练模型、
    低阈值调试或异常权重可能产生大量候选，必须先按分数裁剪，避免
    deployment 子进程被单次请求长时间占住。
    """

    candidate_count = int(scores.shape[0])
    if max_candidate_count <= 0 or candidate_count <= int(max_candidate_count):
        return None
    return np_module.argsort(scores)[-int(max_candidate_count) :][::-1]


__all__ = ["select_top_scoring_candidate_indices"]
