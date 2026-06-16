"""YOLOX core 评估工具入口。"""

from .coco import (
    CocoDetectionMetrics,
    build_coco_per_class_metrics,
    build_zero_coco_per_class_metrics,
    collect_yolox_coco_detections,
    convert_yolox_predictions_to_coco_detections,
    evaluate_coco_detections,
    evaluate_yolox_coco_map,
)
from .pytorch import (
    YOLOX_EVALUATION_DEFAULT_BATCH_SIZE,
    YOLOX_EVALUATION_DEFAULT_NMS_THRESHOLD,
    YOLOX_EVALUATION_DEFAULT_SCORE_THRESHOLD,
    YOLOX_EVALUATION_IMPLEMENTATION_MODE,
    YoloXDetectionEvaluationRequest,
    YoloXDetectionEvaluationResult,
    resolve_yolox_evaluation_device_name,
    resolve_yolox_evaluation_precision,
    resolve_yolox_evaluation_split,
    run_yolox_detection_evaluation,
)
from .validation import evaluate_yolox_validation_losses
from .voc import VocDetectionMetrics

__all__ = [
    "CocoDetectionMetrics",
    "VocDetectionMetrics",
    "YOLOX_EVALUATION_DEFAULT_BATCH_SIZE",
    "YOLOX_EVALUATION_DEFAULT_NMS_THRESHOLD",
    "YOLOX_EVALUATION_DEFAULT_SCORE_THRESHOLD",
    "YOLOX_EVALUATION_IMPLEMENTATION_MODE",
    "YoloXDetectionEvaluationRequest",
    "YoloXDetectionEvaluationResult",
    "build_coco_per_class_metrics",
    "build_zero_coco_per_class_metrics",
    "collect_yolox_coco_detections",
    "convert_yolox_predictions_to_coco_detections",
    "evaluate_coco_detections",
    "evaluate_yolox_coco_map",
    "evaluate_yolox_validation_losses",
    "resolve_yolox_evaluation_device_name",
    "resolve_yolox_evaluation_precision",
    "resolve_yolox_evaluation_split",
    "run_yolox_detection_evaluation",
]
