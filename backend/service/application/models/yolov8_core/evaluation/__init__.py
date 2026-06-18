"""YOLOv8 评估入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.evaluation.classification import (
    evaluate_yolov8_classification_samples,
)
from backend.service.application.models.yolov8_core.evaluation.detection import (
    YoloV8DetectionEvaluationRequest,
    YoloV8DetectionEvaluationResult,
    run_yolov8_detection_evaluation,
)
from backend.service.application.models.yolov8_core.evaluation.obb import (
    YoloV8ObbEvaluationRequest,
    YoloV8ObbEvaluationResult,
    evaluate_yolov8_obb_samples,
    run_yolov8_obb_evaluation,
)
from backend.service.application.models.yolov8_core.evaluation.pose import (
    YoloV8PoseEvaluationRequest,
    YoloV8PoseEvaluationResult,
    evaluate_yolov8_pose_samples,
    run_yolov8_pose_evaluation,
)
from backend.service.application.models.yolov8_core.evaluation.segmentation import (
    YoloV8SegmentationEvaluationRequest,
    YoloV8SegmentationEvaluationResult,
    evaluate_yolov8_segmentation_samples,
    run_yolov8_segmentation_evaluation,
)

__all__ = [
    "YoloV8DetectionEvaluationRequest",
    "YoloV8DetectionEvaluationResult",
    "YoloV8ObbEvaluationRequest",
    "YoloV8ObbEvaluationResult",
    "YoloV8PoseEvaluationRequest",
    "YoloV8PoseEvaluationResult",
    "YoloV8SegmentationEvaluationRequest",
    "YoloV8SegmentationEvaluationResult",
    "evaluate_yolov8_classification_samples",
    "evaluate_yolov8_obb_samples",
    "evaluate_yolov8_pose_samples",
    "evaluate_yolov8_segmentation_samples",
    "run_yolov8_detection_evaluation",
    "run_yolov8_obb_evaluation",
    "run_yolov8_pose_evaluation",
    "run_yolov8_segmentation_evaluation",
]
