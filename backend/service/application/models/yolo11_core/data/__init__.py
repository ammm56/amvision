"""YOLO11 core 数据编码入口。"""

from backend.service.application.models.yolo11_core.data.classification import (
    Yolo11ClassificationTrainingBatch,
    build_yolo11_classification_training_batch,
    load_yolo11_classification_image,
)
from backend.service.application.models.yolo11_core.data.classification_manifest import (
    Yolo11ClassificationTrainingAnnotation,
    Yolo11ClassificationTrainingManifest,
    load_yolo11_classification_training_manifest,
)
from backend.service.application.models.yolo11_core.data.detection import (
    Yolo11DetectionPreparedTarget,
    Yolo11DetectionResolvedSplit,
    Yolo11DetectionTrainingAnnotation,
    Yolo11DetectionTrainingSample,
    build_yolo11_detection_training_batch,
    build_yolo11_detection_training_batch_cpu,
    serialize_yolo11_detection_augmentation_options,
)
from backend.service.application.models.yolo11_core.data.detection_samples import (
    load_yolo11_detection_training_samples,
)
from backend.service.application.models.yolo11_core.data.detection_splits import (
    resolve_yolo11_detection_splits,
    resolve_yolo11_detection_train_split,
    resolve_yolo11_detection_validation_split,
)
from backend.service.application.models.yolo11_core.data.augmentation import (
    Yolo11TaskAugmentationOptions,
    build_yolo11_task_augmentation_options,
    resolve_yolo11_task_augmentation_for_epoch,
    resolve_yolo11_task_batch_input_size,
)
from backend.service.application.models.yolo11_core.data.segmentation import (
    Yolo11SegmentationTrainingBatch,
    build_yolo11_segmentation_training_batch,
)
from backend.service.application.models.yolo11_core.data.pose import (
    Yolo11PoseTrainingBatch,
    build_yolo11_pose_training_batch,
)
from backend.service.application.models.yolo11_core.data.obb import (
    Yolo11ObbTrainingBatch,
    build_yolo11_obb_training_batch,
)

__all__ = [
    "Yolo11ClassificationTrainingBatch",
    "Yolo11ClassificationTrainingAnnotation",
    "Yolo11ClassificationTrainingManifest",
    "Yolo11DetectionPreparedTarget",
    "Yolo11DetectionResolvedSplit",
    "Yolo11DetectionTrainingAnnotation",
    "Yolo11DetectionTrainingSample",
    "Yolo11ObbTrainingBatch",
    "Yolo11PoseTrainingBatch",
    "Yolo11SegmentationTrainingBatch",
    "Yolo11TaskAugmentationOptions",
    "build_yolo11_classification_training_batch",
    "build_yolo11_detection_training_batch",
    "build_yolo11_detection_training_batch_cpu",
    "build_yolo11_obb_training_batch",
    "build_yolo11_pose_training_batch",
    "build_yolo11_segmentation_training_batch",
    "build_yolo11_task_augmentation_options",
    "load_yolo11_classification_image",
    "load_yolo11_classification_training_manifest",
    "load_yolo11_detection_training_samples",
    "resolve_yolo11_task_augmentation_for_epoch",
    "resolve_yolo11_task_batch_input_size",
    "resolve_yolo11_detection_splits",
    "resolve_yolo11_detection_train_split",
    "resolve_yolo11_detection_validation_split",
    "serialize_yolo11_detection_augmentation_options",
]
