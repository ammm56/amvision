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
    """RF-DETR core 类：`RfdetrSegmentationPostProcess`。"""

    def __init__(self, num_select: int = 300) -> None:
        """执行 `__init__`。
        
        参数：
        - `num_select`：传入的 `num_select` 参数。
        
        返回：
        - 当前函数的执行结果。
        """

        super().__init__()
        self.num_select = num_select
        self.upstream_postprocess = UpstreamRfdetrPostProcess(num_select=num_select)

    def forward(
        self,
        outputs: dict[str, torch.Tensor],
        target_sizes: torch.Tensor,
    ) -> dict[str, Any]:
        """执行 `forward`。
        
        参数：
        - `outputs`：传入的 `outputs` 参数。
        - `target_sizes`：传入的 `target_sizes` 参数。
        
        返回：
        - 当前函数的执行结果。
        """

        return self.postprocess(outputs, target_sizes)

    def postprocess(
        self,
        outputs: dict[str, torch.Tensor],
        target_sizes: torch.Tensor,
    ) -> dict[str, Any]:
        """执行 `postprocess`。
        
        参数：
        - `outputs`：传入的 `outputs` 参数。
        - `target_sizes`：传入的 `target_sizes` 参数。
        
        返回：
        - 当前函数的执行结果。
        """

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
    """执行 `build_rfdetr_segmentation_model`。
    
    参数：
    - `model_scale`：传入的 `model_scale` 参数。
    - `num_classes`：传入的 `num_classes` 参数。
    - `pretrained_path`：传入的 `pretrained_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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
    """执行 `build_rfdetr_segmentation_postprocess`。
    
    参数：
    - `num_select`：传入的 `num_select` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return RfdetrSegmentationPostProcess(num_select=num_select)


def mask_logits_to_xyxy(masks: torch.Tensor) -> torch.Tensor:
    """执行 `mask_logits_to_xyxy`。
    
    参数：
    - `masks`：传入的 `masks` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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
    """执行 `masks_xyxy_to_cxcywh`。
    
    参数：
    - `boxes_xyxy`：传入的 `boxes_xyxy` 参数。
    - `image_size`：传入的 `image_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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
