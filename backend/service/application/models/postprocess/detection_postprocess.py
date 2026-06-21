"""detection 公共后处理规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.postprocess import (
    prepare_detection_nms_inputs_array,
)
from backend.service.application.runtime.support.detection import batched_nms_indices


DETECTION_POSTPROCESS_MODE_NMS = "nms"
DETECTION_POSTPROCESS_MODE_END2END_TOPK = "end2end-topk"
DEFAULT_END2END_MAX_DETECTIONS = 300
DetectionPostprocessMode = Literal["nms", "end2end-topk"]
DetectionBoxFormat = Literal["xyxy", "xywh"]


@dataclass(frozen=True)
class DetectionPostprocessResult:
    """描述单张图片经过统一 detection 后处理后的候选结果。"""

    boxes_xyxy: Any
    scores: Any
    class_ids: Any


def postprocess_detection_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
    nms_threshold: float,
    postprocess_mode: DetectionPostprocessMode = DETECTION_POSTPROCESS_MODE_NMS,
    box_format: DetectionBoxFormat = "xyxy",
    max_detections: int | None = None,
) -> list[DetectionPostprocessResult | None]:
    """执行 detection 预测数组的统一后处理。"""

    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_prediction.ndim < 3:
        raise InvalidRequestError(
            "detection 推理输出维度不合法",
            details={"shape": list(normalized_prediction.shape)},
        )
    required_channel_count = 4 + int(num_classes)
    if int(normalized_prediction.shape[1]) >= required_channel_count and int(
        normalized_prediction.shape[2]
    ) > int(normalized_prediction.shape[1]):
        # Ultralytics export 模式输出为 [B, C, N]，平台后处理统一按 [B, N, C] 消费。
        normalized_prediction = np_module.transpose(normalized_prediction, (0, 2, 1))
    if int(normalized_prediction.shape[2]) < 4 + num_classes:
        raise InvalidRequestError(
            "detection 推理输出通道数不足",
            details={
                "channel_count": int(normalized_prediction.shape[2]),
                "required_channel_count": 4 + num_classes,
            },
        )

    resolved_max_detections = max(
        1,
        int(max_detections or DEFAULT_END2END_MAX_DETECTIONS),
    )
    results: list[DetectionPostprocessResult | None] = []
    for image_prediction in normalized_prediction:
        nms_inputs = prepare_detection_nms_inputs_array(
            image_prediction=image_prediction,
            np_module=np_module,
            num_classes=num_classes,
            score_threshold=score_threshold,
            box_format=box_format,
        )
        if nms_inputs is None:
            results.append(None)
            continue

        if postprocess_mode == DETECTION_POSTPROCESS_MODE_END2END_TOPK:
            actual_k = min(resolved_max_detections, int(nms_inputs.boxes_xyxy.shape[0]))
            keep_indices = np_module.argsort(nms_inputs.scores)[::-1][:actual_k]
        elif postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS:
            keep_indices = batched_nms_indices(
                boxes=nms_inputs.boxes_xyxy,
                scores=nms_inputs.scores,
                class_ids=nms_inputs.class_ids,
                nms_threshold=nms_threshold,
                np_module=np_module,
            )
        else:
            raise InvalidRequestError(
                "当前 detection 后处理模式不受支持",
                details={"postprocess_mode": postprocess_mode},
            )
        if int(keep_indices.size) <= 0:
            results.append(None)
            continue
        results.append(
            DetectionPostprocessResult(
                boxes_xyxy=nms_inputs.boxes_xyxy[keep_indices],
                scores=nms_inputs.scores[keep_indices],
                class_ids=nms_inputs.class_ids[keep_indices],
            )
        )
    return results
