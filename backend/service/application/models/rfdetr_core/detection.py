"""RF-DETR core detection 任务适配模块：`detection`。"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from backend.service.application.models.rfdetr_core.factory import (
    build_rfdetr_full_core_model,
)
from backend.service.application.models.rfdetr_core.models.postprocess import (
    PostProcess as UpstreamRfdetrPostProcess,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE


class RfdetrPostProcess(nn.Module):
    """把 RF-DETR 原始输出整理成 detection runtime 使用的张量结构。"""

    def __init__(self, num_select: int = 300) -> None:
        """初始化 top-k 选择数量和 RF-DETR 原生 postprocess。"""

        super().__init__()
        self.num_select = num_select
        self.upstream_postprocess = UpstreamRfdetrPostProcess(num_select=num_select)

    def forward(
        self,
        outputs: dict[str, torch.Tensor],
        target_sizes: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        """执行 detection 后处理前向。"""

        return self.postprocess(outputs, target_sizes)

    def postprocess(
        self,
        outputs: dict[str, torch.Tensor],
        target_sizes: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        """把 logits 和 normalized boxes 转成分数、类别和 xyxy boxes。"""

        results = self.upstream_postprocess(outputs, target_sizes)
        top_scores = torch.stack([item["scores"] for item in results], dim=0)
        top_labels = torch.stack([item["labels"] for item in results], dim=0)
        boxes_xyxy = torch.stack([item["boxes"] for item in results], dim=0)
        payload: dict[str, torch.Tensor] = {
            "scores": top_scores,
            "labels": top_labels,
            "boxes_xyxy": boxes_xyxy,
        }
        if all("masks" in item for item in results):
            payload["masks"] = torch.stack([item["masks"] for item in results], dim=0)
        return payload


def build_rfdetr_model(
    *,
    model_scale: str = "nano",
    num_classes: int = 91,
    pretrained_path: str | None = None,
) -> torch.nn.Module:
    """构建 RF-DETR detection full core 模型并挂载 runtime postprocess。"""

    model = build_rfdetr_full_core_model(
        task_type=DETECTION_TASK_TYPE,
        model_scale=model_scale,
        num_classes=num_classes,
        pretrained_path=pretrained_path,
    )
    model.postprocess = RfdetrPostProcess()  # type: ignore[attr-defined]
    return model


def build_rfdetr_postprocess(num_select: int = 300) -> RfdetrPostProcess:
    """构建 detection runtime 使用的 RF-DETR postprocess 模块。"""

    return RfdetrPostProcess(num_select=num_select)


def _box_cxcywh_to_xyxy(boxes: torch.Tensor) -> torch.Tensor:
    """把 cxcywh box 转成 xyxy box。"""

    center_x, center_y, width, height = boxes.unbind(-1)
    return torch.stack(
        [
            center_x - width / 2,
            center_y - height / 2,
            center_x + width / 2,
            center_y + height / 2,
        ],
        dim=-1,
    )


def sigmoid_focal_loss(
    inputs: torch.Tensor,
    targets: torch.Tensor,
    alpha: float = 0.25,
    gamma: float = 2.0,
) -> torch.Tensor:
    """计算 detection 分类分支使用的 sigmoid focal loss。"""

    prob = inputs.sigmoid()
    ce = F.binary_cross_entropy_with_logits(inputs, targets, reduction="none")
    p_t = prob * targets + (1 - prob) * (1 - targets)
    loss = ce * ((1 - p_t) ** gamma)
    alpha_t = alpha * targets + (1 - alpha) * (1 - targets)
    return (alpha_t * loss).sum(dim=1).mean()


__all__ = [
    "RfdetrPostProcess",
    "_box_cxcywh_to_xyxy",
    "build_rfdetr_model",
    "build_rfdetr_postprocess",
    "sigmoid_focal_loss",
]
