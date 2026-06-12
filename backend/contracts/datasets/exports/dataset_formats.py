"""数据集导出格式定义。"""

from __future__ import annotations

from typing import Final, Literal


# 当前规划支持的数据集导出格式 id。
DatasetExportFormatId = Literal[
    "yolo-detection-v1",
    "yolo-instance-seg-v1",
    "yolo-pose-v1",
    "coco-detection-v1",
    "voc-detection-v1",
    "coco-instance-seg-v1",
    "coco-keypoints-v1",
    "semantic-mask-dir-v1",
    "sam-promptable-seg-v1",
    "imagenet-classification-v1",
    "dota-obb-v1",
]


YOLO_DETECTION_DATASET_FORMAT: Final[DatasetExportFormatId] = "yolo-detection-v1"
YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT: Final[DatasetExportFormatId] = (
    "yolo-instance-seg-v1"
)
YOLO_POSE_DATASET_FORMAT: Final[DatasetExportFormatId] = "yolo-pose-v1"
COCO_DETECTION_DATASET_FORMAT: Final[DatasetExportFormatId] = "coco-detection-v1"
VOC_DETECTION_DATASET_FORMAT: Final[DatasetExportFormatId] = "voc-detection-v1"
COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT: Final[DatasetExportFormatId] = (
    "coco-instance-seg-v1"
)
COCO_KEYPOINTS_DATASET_FORMAT: Final[DatasetExportFormatId] = "coco-keypoints-v1"
SEMANTIC_MASK_DIRECTORY_DATASET_FORMAT: Final[DatasetExportFormatId] = "semantic-mask-dir-v1"
SAM_PROMPTABLE_SEGMENTATION_DATASET_FORMAT: Final[DatasetExportFormatId] = (
    "sam-promptable-seg-v1"
)
IMAGENET_CLASSIFICATION_DATASET_FORMAT: Final[DatasetExportFormatId] = "imagenet-classification-v1"
DOTA_OBB_DATASET_FORMAT: Final[DatasetExportFormatId] = "dota-obb-v1"


# 当前规划支持的全部数据集导出格式。
SUPPORTED_DATASET_EXPORT_FORMATS: Final[tuple[DatasetExportFormatId, ...]] = (
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
    COCO_DETECTION_DATASET_FORMAT,
    VOC_DETECTION_DATASET_FORMAT,
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    COCO_KEYPOINTS_DATASET_FORMAT,
    SEMANTIC_MASK_DIRECTORY_DATASET_FORMAT,
    SAM_PROMPTABLE_SEGMENTATION_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    DOTA_OBB_DATASET_FORMAT,
)


# 当前已经正式实现并可对外开放的数据集导出格式。
IMPLEMENTED_DATASET_EXPORT_FORMATS: Final[tuple[DatasetExportFormatId, ...]] = (
    COCO_DETECTION_DATASET_FORMAT,
    VOC_DETECTION_DATASET_FORMAT,
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    COCO_KEYPOINTS_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    DOTA_OBB_DATASET_FORMAT,
)
