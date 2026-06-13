"""YOLO 主线 detection decode 边界。"""

from __future__ import annotations

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
