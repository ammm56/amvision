"""项目内 YOLOX loss 组件。"""

from __future__ import annotations

import torch
import torch.nn as nn


class IOUloss(nn.Module):
    """实现 YOLOX head 使用的 IoU / GIoU loss。"""

    def __init__(self, reduction: str = "none", loss_type: str = "iou") -> None:
        """初始化 IOUloss。"""

        super().__init__()
        self.reduction = reduction
        self.loss_type = loss_type

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """计算预测框与目标框之间的 IoU 类损失。"""

        if pred.shape[0] != target.shape[0]:
            raise AssertionError("pred 与 target 的 batch 维必须一致")

        pred = pred.view(-1, 4)
        target = target.view(-1, 4)
        top_left = torch.max(pred[:, :2] - pred[:, 2:] / 2, target[:, :2] - target[:, 2:] / 2)
        bottom_right = torch.min(
            pred[:, :2] + pred[:, 2:] / 2,
            target[:, :2] + target[:, 2:] / 2,
        )

        area_pred = torch.prod(pred[:, 2:], 1)
        area_target = torch.prod(target[:, 2:], 1)
        overlap_mask = (top_left < bottom_right).type(top_left.type()).prod(dim=1)
        area_intersection = torch.prod(bottom_right - top_left, 1) * overlap_mask
        area_union = area_pred + area_target - area_intersection
        iou = area_intersection / (area_union + 1e-16)

        if self.loss_type == "iou":
            loss = 1 - iou**2
        elif self.loss_type == "giou":
            closure_top_left = torch.min(pred[:, :2] - pred[:, 2:] / 2, target[:, :2] - target[:, 2:] / 2)
            closure_bottom_right = torch.max(
                pred[:, :2] + pred[:, 2:] / 2,
                target[:, :2] + target[:, 2:] / 2,
            )
            closure_area = torch.prod(closure_bottom_right - closure_top_left, 1)
            giou = iou - (closure_area - area_union) / closure_area.clamp(1e-16)
            loss = 1 - giou.clamp(min=-1.0, max=1.0)
        else:
            raise ValueError(f"不支持的 IOU loss 类型: {self.loss_type}")

        if self.reduction == "mean":
            return loss.mean()
        if self.reduction == "sum":
            return loss.sum()
        return loss