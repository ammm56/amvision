"""YOLO 主线 loss 中的 assignment 写入规则。"""

from __future__ import annotations

from typing import Any


def write_assignment_quality_scores(
    *,
    target_scores: Any,
    foreground_mask: Any,
    gt_classes: Any,
    assigned_gt_indices: Any,
    quality_scores: Any,
) -> None:
    """把 TAL quality score 按目标张量的 device/dtype 安全写入。

    ProbIoU、CIoU 等稳定性计算可能在 autocast 内返回 FP32，而分类 logits
    和 ``target_scores`` 是 FP16；索引赋值不会自动执行 dtype promotion。
    """

    target_scores[foreground_mask, gt_classes[assigned_gt_indices]] = (
        quality_scores.to(device=target_scores.device, dtype=target_scores.dtype)
    )


__all__ = ["write_assignment_quality_scores"]
