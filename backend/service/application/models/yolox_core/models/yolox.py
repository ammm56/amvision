"""项目内 YOLOX 总模型封装。"""

from __future__ import annotations

import torch.nn as nn

from .yolo_head import YOLOXHead
from .yolo_pafpn import YOLOPAFPN


class YOLOX(nn.Module):
    """封装 backbone 与 head 的 YOLOX 主模型。"""

    def __init__(self, backbone: nn.Module | None = None, head: nn.Module | None = None) -> None:
        """初始化 YOLOX 主模型。"""

        super().__init__()
        self.backbone = backbone if backbone is not None else YOLOPAFPN()
        self.head = head if head is not None else YOLOXHead(80)

    def forward(self, x, targets=None):
        """执行 YOLOX 前向；训练态返回 loss 字典，推理态返回预测张量。"""

        fpn_outs = self.backbone(x)
        if self.training:
            if targets is None:
                raise AssertionError("训练态前向必须提供 targets")
            loss, iou_loss, conf_loss, cls_loss, l1_loss, num_fg = self.head(fpn_outs, targets, x)
            return {
                "total_loss": loss,
                "iou_loss": iou_loss,
                "l1_loss": l1_loss,
                "conf_loss": conf_loss,
                "cls_loss": cls_loss,
                "num_fg": num_fg,
            }
        return self.head(fpn_outs)

    def visualize(self, x, targets, save_prefix: str = "assign_vis_") -> None:
        """输出标签分配可视化结果。"""

        fpn_outs = self.backbone(x)
        self.head.visualize_assign_result(fpn_outs, targets, x, save_prefix)