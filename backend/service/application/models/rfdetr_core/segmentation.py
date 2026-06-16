"""RF-DETR core segmentation 任务适配模块：`segmentation`。"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from backend.service.application.models.rfdetr_core.factory import (
    build_rfdetr_full_core_model,
)
from backend.service.application.models.rfdetr_core.models.postprocess import (
    PostProcess as UpstreamRfdetrPostProcess,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE


class RfdetrSegmentationPostProcess(nn.Module):
    """把 RF-DETR segmentation 原始输出整理成 runtime 使用的张量结构。"""

    def __init__(self, num_select: int = 300) -> None:
        """初始化 top-k 选择数量和 RF-DETR 原生 postprocess。"""

        super().__init__()
        self.num_select = num_select
        self.upstream_postprocess = UpstreamRfdetrPostProcess(num_select=num_select)

    def forward(
        self,
        outputs: dict[str, torch.Tensor],
        target_sizes: torch.Tensor,
    ) -> dict[str, Any]:
        """执行 segmentation 后处理前向。"""

        return self.postprocess(outputs, target_sizes)

    def postprocess(
        self,
        outputs: dict[str, torch.Tensor],
        target_sizes: torch.Tensor,
    ) -> dict[str, Any]:
        """把 logits、boxes 和 masks 转成 runtime 统一输出字段。"""

        results = self.upstream_postprocess(outputs, target_sizes)
        top_scores = torch.stack([item["scores"] for item in results], dim=0)
        top_labels = torch.stack([item["labels"] for item in results], dim=0)
        boxes_xyxy = torch.stack([item["boxes"] for item in results], dim=0)
        payload: dict[str, Any] = {
            "scores": top_scores,
            "labels": top_labels,
            "boxes_xyxy": boxes_xyxy,
        }
        if all("masks" in item for item in results):
            payload["masks"] = torch.stack([item["masks"] for item in results], dim=0)
        return payload


def build_rfdetr_segmentation_model(
    *,
    model_scale: str = "nano",
    num_classes: int = 91,
    pretrained_path: str | None = None,
) -> torch.nn.Module:
    """构建 RF-DETR segmentation full core 模型并挂载 runtime postprocess。"""

    model = build_rfdetr_full_core_model(
        task_type=SEGMENTATION_TASK_TYPE,
        model_scale=model_scale,
        num_classes=num_classes,
        pretrained_path=pretrained_path,
    )
    model.postprocess = RfdetrSegmentationPostProcess()  # type: ignore[attr-defined]
    return model


def build_rfdetr_segmentation_postprocess(
    num_select: int = 300,
) -> RfdetrSegmentationPostProcess:
    """构建 segmentation runtime 使用的 RF-DETR postprocess 模块。"""

    return RfdetrSegmentationPostProcess(num_select=num_select)


def mask_logits_to_xyxy(masks: torch.Tensor) -> torch.Tensor:
    """根据 mask logits 的前景范围估算 xyxy box。"""

    binary_masks = masks > 0.0
    batch_boxes: list[torch.Tensor] = []
    for per_image_masks in binary_masks:
        if per_image_masks.numel() == 0:
            batch_boxes.append(
                torch.zeros((0, 4), dtype=torch.float32, device=masks.device)
            )
            continue
        per_mask_boxes: list[torch.Tensor] = []
        for mask in per_image_masks:
            coords = torch.nonzero(mask, as_tuple=False)
            if coords.numel() == 0:
                per_mask_boxes.append(
                    torch.zeros((4,), dtype=torch.float32, device=masks.device)
                )
                continue
            y_min = coords[:, 0].min().float()
            x_min = coords[:, 1].min().float()
            y_max = coords[:, 0].max().float()
            x_max = coords[:, 1].max().float()
            per_mask_boxes.append(torch.stack([x_min, y_min, x_max, y_max]))
        batch_boxes.append(torch.stack(per_mask_boxes, dim=0))
    return torch.stack(batch_boxes, dim=0)


def masks_xyxy_to_cxcywh(
    boxes_xyxy: torch.Tensor,
    image_size: tuple[int, int],
) -> torch.Tensor:
    """把像素坐标 xyxy box 转成归一化 cxcywh box。"""

    image_height, image_width = image_size
    x1, y1, x2, y2 = boxes_xyxy.unbind(-1)
    cx = ((x1 + x2) / 2.0) / max(1.0, float(image_width))
    cy = ((y1 + y2) / 2.0) / max(1.0, float(image_height))
    width = (x2 - x1).clamp(min=0.0) / max(1.0, float(image_width))
    height = (y2 - y1).clamp(min=0.0) / max(1.0, float(image_height))
    return torch.stack([cx, cy, width, height], dim=-1)


__all__ = [
    "RfdetrSegmentationPostProcess",
    "build_rfdetr_segmentation_model",
    "build_rfdetr_segmentation_postprocess",
    "mask_logits_to_xyxy",
    "masks_xyxy_to_cxcywh",
]
