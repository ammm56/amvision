"""YOLOv8 数据处理入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.data.classification import (
    YoloV8ClassificationTrainingBatch,
    build_yolov8_classification_training_batch,
    load_yolov8_classification_image,
)
from backend.service.application.models.yolov8_core.data.augmentation import (
    YoloV8TaskAugmentationOptions,
    build_yolov8_task_augmentation_options,
    resolve_yolov8_task_augmentation_for_epoch,
    resolve_yolov8_task_batch_input_size,
)
from backend.service.application.models.yolov8_core.data.detection import (
    YoloV8DetectionAugmentationOptions,
    YoloV8DetectionPreparedTarget,
    YoloV8DetectionResolvedSplit,
    YoloV8DetectionTrainingAnnotation,
    YoloV8DetectionTrainingSample,
    build_yolov8_detection_training_batch,
    load_yolov8_detection_training_samples,
    resolve_yolov8_detection_splits,
    resolve_yolov8_detection_train_split,
    resolve_yolov8_detection_validation_split,
)
from backend.service.application.models.yolov8_core.data.obb import (
    YoloV8ObbPreparedTarget,
    YoloV8ObbTrainingBatch,
    build_yolov8_obb_training_batch,
)
from backend.service.application.models.yolov8_core.data.pose import (
    YoloV8PosePreparedTarget,
    YoloV8PoseTrainingBatch,
    build_yolov8_pose_training_batch,
)
from backend.service.application.models.yolov8_core.data.segmentation import (
    YoloV8SegmentationTrainingBatch,
    build_yolov8_segmentation_training_batch,
)

__all__ = [
    "YoloV8ClassificationTrainingBatch",
    "YoloV8DetectionAugmentationOptions",
    "YoloV8TaskAugmentationOptions",
    "YoloV8DetectionPreparedTarget",
    "YoloV8DetectionResolvedSplit",
    "YoloV8DetectionTrainingAnnotation",
    "YoloV8DetectionTrainingSample",
    "YoloV8ObbPreparedTarget",
    "YoloV8ObbTrainingBatch",
    "YoloV8PosePreparedTarget",
    "YoloV8PoseTrainingBatch",
    "YoloV8SegmentationTrainingBatch",
    "build_yolov8_classification_training_batch",
    "build_yolov8_detection_training_batch",
    "build_yolov8_obb_training_batch",
    "build_yolov8_pose_training_batch",
    "build_yolov8_segmentation_training_batch",
    "build_yolov8_task_augmentation_options",
    "load_yolov8_classification_image",
    "load_yolov8_detection_training_samples",
    "resolve_yolov8_detection_splits",
    "resolve_yolov8_detection_train_split",
    "resolve_yolov8_detection_validation_split",
    "resolve_yolov8_task_augmentation_for_epoch",
    "resolve_yolov8_task_batch_input_size",
]
