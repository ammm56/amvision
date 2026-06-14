"""YOLO 主线 detection loss 辅助函数。"""

from __future__ import annotations

from typing import Any


def distribution_focal_loss(
    *,
    torch_module: Any,
    logits: Any,
    target: Any,
) -> Any:
    """计算 DFL 损失。"""

    reg_max = int(logits.shape[2])
    target_left = target.clamp(0, reg_max - 1 - 0.01).floor().long()
    target_right = (target_left + 1).clamp(0, reg_max - 1)
    weight_left = target_right.to(target.dtype) - target
    weight_right = 1.0 - weight_left
    flat_logits = logits.reshape(-1, reg_max)
    loss_left = torch_module.nn.functional.cross_entropy(
        flat_logits,
        target_left.reshape(-1),
        reduction="none",
    )
    loss_right = torch_module.nn.functional.cross_entropy(
        flat_logits,
        target_right.reshape(-1),
        reduction="none",
    )
    combined = (
        loss_left * weight_left.reshape(-1)
        + loss_right * weight_right.reshape(-1)
    )
    return combined.view(-1, 4).sum(dim=1)
