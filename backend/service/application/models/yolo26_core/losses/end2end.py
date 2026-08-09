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
    """按 Ultralytics E2ELoss 语义合并 YOLO26 loss payload。

    反向传播总 loss 按动态权重合并 one-to-many 和 one-to-one；用于报告的
    各分项保持 one-to-one 分支口径，与参考实现返回的 ``loss_one2one[1]``
    一致，避免把报告字段误当成两个分支总 loss 的可加和拆解。
    """

    if "loss" not in one2many_payload or "loss" not in one2one_payload:
        # segmentation 的底层 helper 先返回未加 gain 的 component payload，
        # 上层再构造总 loss。该内部边界仍需按分支权重线性合并；完整 task
        # payload 一旦包含 loss，则严格采用 reference 的 one-to-one 报告口径。
        return {
            key: (
                value * float(one2many_weight)
                + one2one_payload[key] * float(one2one_weight)
            )
            for key, value in one2many_payload.items()
            if key in one2one_payload
        }
    combined: dict[str, Any] = {
        key: value for key, value in one2one_payload.items() if key != "loss"
    }
    combined["loss"] = (
        one2many_payload["loss"] * float(one2many_weight)
        + one2one_payload["loss"] * float(one2one_weight)
    )
    return combined


__all__ = [
    "combine_yolo26_end2end_loss_payloads",
    "resolve_yolo26_end2end_loss_weights",
]
