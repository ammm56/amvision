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
    """RF-DETR core 类：`RfdetrPostProcess`。"""

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
    ) -> dict[str, torch.Tensor]:
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
    ) -> dict[str, torch.Tensor]:
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
    """执行 `build_rfdetr_model`。
    
    参数：
    - `model_scale`：传入的 `model_scale` 参数。
    - `num_classes`：传入的 `num_classes` 参数。
    - `pretrained_path`：传入的 `pretrained_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    model = build_rfdetr_full_core_model(
        task_type=DETECTION_TASK_TYPE,
        model_scale=model_scale,
        num_classes=num_classes,
        pretrained_path=pretrained_path,
    )
    model.postprocess = RfdetrPostProcess()  # type: ignore[attr-defined]
    return model


def build_rfdetr_postprocess(num_select: int = 300) -> RfdetrPostProcess:
    """执行 `build_rfdetr_postprocess`。
    
    参数：
    - `num_select`：传入的 `num_select` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return RfdetrPostProcess(num_select=num_select)


def _box_cxcywh_to_xyxy(boxes: torch.Tensor) -> torch.Tensor:
    """执行 `_box_cxcywh_to_xyxy`。
    
    参数：
    - `boxes`：传入的 `boxes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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
    """执行 `sigmoid_focal_loss`。
    
    参数：
    - `inputs`：传入的 `inputs` 参数。
    - `targets`：传入的 `targets` 参数。
    - `alpha`：传入的 `alpha` 参数。
    - `gamma`：传入的 `gamma` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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
