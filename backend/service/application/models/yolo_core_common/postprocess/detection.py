"""YOLO 主线 detection NMS 前置后处理。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class DetectionNmsInputArrays:
    """描述单张图片进入 NMS 前的数组候选结果。"""

    boxes_xyxy: Any
    scores: Any
    class_ids: Any


@dataclass(frozen=True)
class DetectionNmsInputTensors:
    """描述批量预测进入 NMS 前的 tensor 候选结果。"""

    boxes_xyxy: torch.Tensor
    scores: torch.Tensor
    class_ids: torch.Tensor
    batch_indices: torch.Tensor


def prepare_detection_nms_inputs_array(
    *,
    image_prediction: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
) -> DetectionNmsInputArrays | None:
    """从单张 detection 预测数组中筛出进入 NMS 的候选框。"""

    _validate_detection_prediction_channel_count(
        channel_count=int(image_prediction.shape[1]),
        num_classes=num_classes,
    )
    boxes = image_prediction[:, :4]
    class_scores = image_prediction[:, 4 : 4 + num_classes]
    best_scores = np_module.max(class_scores, axis=1)
    best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
    keep_mask = best_scores >= score_threshold
    boxes = boxes[keep_mask]
    best_scores = best_scores[keep_mask]
    best_class_ids = best_class_ids[keep_mask]
    if int(boxes.shape[0]) <= 0:
        return None
    return DetectionNmsInputArrays(
        boxes_xyxy=boxes,
        scores=best_scores,
        class_ids=best_class_ids,
    )


def prepare_detection_nms_inputs_tensor(
    *,
    prediction_tensor: torch.Tensor,
    num_classes: int,
    score_threshold: float,
) -> DetectionNmsInputTensors | None:
    """从批量 detection 预测 tensor 中筛出进入 NMS 的候选框。"""

    if prediction_tensor.ndim != 3:
        raise InvalidRequestError(
            "detection 推理输出维度不合法",
            details={"shape": list(prediction_tensor.shape)},
        )
    _validate_detection_prediction_channel_count(
        channel_count=int(prediction_tensor.shape[2]),
        num_classes=num_classes,
    )
    boxes = prediction_tensor[..., :4]
    class_scores = prediction_tensor[..., 4 : 4 + num_classes]
    best_scores, best_class_ids = class_scores.max(dim=2)
    keep_mask = best_scores >= float(score_threshold)
    selected_indices = keep_mask.nonzero(as_tuple=False)
    if int(selected_indices.shape[0]) <= 0:
        return None
    batch_indices = selected_indices[:, 0]
    anchor_indices = selected_indices[:, 1]
    return DetectionNmsInputTensors(
        boxes_xyxy=boxes[batch_indices, anchor_indices],
        scores=best_scores[batch_indices, anchor_indices],
        class_ids=best_class_ids[batch_indices, anchor_indices],
        batch_indices=batch_indices,
    )


def _validate_detection_prediction_channel_count(
    *,
    channel_count: int,
    num_classes: int,
) -> None:
    """校验 detection 预测通道数是否包含 box 与类别分数。"""

    required_channel_count = 4 + int(num_classes)
    if int(channel_count) < required_channel_count:
        raise InvalidRequestError(
            "detection 推理输出通道数不足",
            details={
                "channel_count": int(channel_count),
                "required_channel_count": required_channel_count,
            },
        )
