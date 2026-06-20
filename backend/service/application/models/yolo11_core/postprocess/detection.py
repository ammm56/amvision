"""YOLO11 detection 后处理入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.detection_postprocess import (
    DETECTION_POSTPROCESS_MODE_NMS,
    postprocess_detection_prediction_array,
)
from backend.service.application.runtime.contracts.detection import (
    DetectionPredictionDetection,
)


YOLO11_DETECTION_POSTPROCESS_MODE_NMS = DETECTION_POSTPROCESS_MODE_NMS


def build_yolo11_detection_records(
    *,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    nms_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
) -> tuple[DetectionPredictionDetection, ...]:
    """把 YOLO11 detection 输出转换成平台 detection 记录。"""

    postprocess_results = postprocess_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(labels),
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        postprocess_mode=YOLO11_DETECTION_POSTPROCESS_MODE_NMS,
        box_format="xywh",
        max_detections=None,
    )
    if not postprocess_results:
        return ()

    prediction = postprocess_results[0]
    if prediction is None:
        return ()

    detections: list[DetectionPredictionDetection] = []
    for bbox, score, class_id in zip(
        prediction.boxes_xyxy,
        prediction.scores,
        prediction.class_ids,
        strict=True,
    ):
        scaled_bbox = bbox / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(scaled_bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(scaled_bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(scaled_bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(scaled_bbox[3]), float(image_height))))
        resolved_class_id = int(class_id)
        class_name = (
            labels[resolved_class_id] if 0 <= resolved_class_id < len(labels) else None
        )
        detections.append(
            DetectionPredictionDetection(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(float(score), 6),
                class_id=resolved_class_id,
                class_name=class_name,
            )
        )
    detections.sort(key=lambda item: item.score, reverse=True)
    return tuple(detections)


__all__ = [
    "YOLO11_DETECTION_POSTPROCESS_MODE_NMS",
    "build_yolo11_detection_records",
]
