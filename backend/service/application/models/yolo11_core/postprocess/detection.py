"""YOLO11 detection 后处理入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.postprocess.detection_postprocess import (
    DETECTION_POSTPROCESS_MODE_NMS,
    postprocess_detection_prediction_array,
)
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
    scale_yolo_box_from_letterbox,
)
from backend.service.application.runtime.contracts.detection.prediction import (
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
    letterbox_transform: YoloLetterboxTransform,
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
        scaled_bbox = scale_yolo_box_from_letterbox(
            box_xyxy=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
            transform=letterbox_transform,
        )
        if scaled_bbox is None:
            continue
        x1, y1, x2, y2 = scaled_bbox
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
