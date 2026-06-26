"""YOLO26 end2end loss 组合规则。"""

from __future__ import annotations

from typing import Any


def resolve_yolo26_end2end_loss_weights(
    *,
    epoch: int,
    max_epochs: int,
) -> tuple[float, float]:
    """按 Ultralytics YOLO26 规则解析 one2many / one2one loss 权重。"""

    update_index = max(0, int(epoch) - 1)
    epoch_count = max(int(max_epochs) - 1, 1)
    one2many_weight = (
        max(1.0 - update_index / epoch_count, 0.0) * (0.8 - 0.1) + 0.1
    )
    one2one_weight = max(1.0 - one2many_weight, 0.0)
    return one2many_weight, one2one_weight


def combine_yolo26_end2end_loss_payloads(
    *,
    one2many_payload: dict[str, Any],
    one2one_payload: dict[str, Any],
    one2many_weight: float,
    one2one_weight: float,
) -> dict[str, Any]:
    """合并 YOLO26 end2end one2many / one2one loss payload。"""

    combined: dict[str, Any] = {}
    for key, one2many_value in one2many_payload.items():
        if key not in one2one_payload:
            continue
        one2one_value = one2one_payload[key]
        combined[key] = (
            one2many_value * float(one2many_weight)
            + one2one_value * float(one2one_weight)
        )
    return combined


__all__ = [
    "combine_yolo26_end2end_loss_payloads",
    "resolve_yolo26_end2end_loss_weights",
]
