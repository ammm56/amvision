"""YOLO 主线 detection decode 边界。"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn

from backend.service.application.models.yolo_core_common.geometry import (
    dist2bbox_xyxy,
    make_anchors,
)


def decode_detection_boxes(
    *,
    raw_outputs: dict[str, torch.Tensor],
    strides: tuple[int, ...],
    dfl_decoder: nn.Module,
) -> torch.Tensor:
    """把 detection head 原始 box 分布解码成 xyxy 边界框。"""

    anchor_points, stride_tensor = make_anchors(
        feature_maps=raw_outputs["feats"],
        strides=strides,
    )
    distances = dfl_decoder(raw_outputs["boxes"])
    return dist2bbox_xyxy(
        distances=distances,
        anchor_points=anchor_points.unsqueeze(0),
        stride_tensor=stride_tensor.unsqueeze(0),
    )


def build_detection_prediction(
    *,
    raw_outputs: dict[str, torch.Tensor],
    strides: tuple[int, ...],
    dfl_decoder: nn.Module,
) -> torch.Tensor:
    """把 detection head 原始输出组装成推理预测张量。"""

    decoded_boxes = decode_detection_boxes(
        raw_outputs=raw_outputs,
        strides=strides,
        dfl_decoder=dfl_decoder,
    )
    class_scores = raw_outputs["scores"].sigmoid()
    return torch.cat((decoded_boxes, class_scores), dim=1)


def decode_detection_training_predictions(
    *,
    torch_module: Any,
    detect_head: Any,
    raw_outputs: dict[str, torch.Tensor],
) -> dict[str, torch.Tensor]:
    """把训练阶段原始输出解码成 loss 可直接消费的预测结构。"""

    distance_logits = raw_outputs["boxes"].permute(0, 2, 1).contiguous()
    if int(getattr(detect_head, "reg_max")) > 1:
        distances = detect_head.dfl(raw_outputs["boxes"])
    else:
        distances = torch_module.nn.functional.softplus(raw_outputs["boxes"])
    anchor_points, stride_tensor = make_anchors(
        feature_maps=raw_outputs["feats"],
        strides=tuple(int(item) for item in getattr(detect_head, "strides")),
    )
    decoded_boxes = dist2bbox_xyxy(
        distances=distances,
        anchor_points=anchor_points.unsqueeze(0),
        stride_tensor=stride_tensor.unsqueeze(0),
    )
    anchor_centers_xy = anchor_points * stride_tensor
    return {
        "distance_logits": distance_logits,
        "boxes_xyxy": decoded_boxes.permute(0, 2, 1).contiguous(),
        "class_logits": raw_outputs["scores"].permute(0, 2, 1).contiguous(),
        "anchor_points": anchor_points,
        "stride_tensor": stride_tensor,
        "anchor_centers_xy": anchor_centers_xy,
        "reg_max": int(getattr(detect_head, "reg_max")),
    }
