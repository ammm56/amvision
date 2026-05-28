"""YOLO detection 数据集导出定义。"""

from __future__ import annotations
from dataclasses import dataclass, field
from backend.contracts.datasets.exports.dataset_formats import YOLO_DETECTION_DATASET_FORMAT as yolo_det, YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT as yolo_seg, YOLO_POSE_DATASET_FORMAT as yolo_pose

@dataclass(frozen=True)
class YoloExportSplit:
    name: str; image_root: str; label_root: str; sample_count: int

@dataclass(frozen=True)
class YoloDetectionExportManifest:
    dataset_version_id: str; format_id: str = yolo_det
    category_names: tuple[str, ...] = (); splits: tuple[YoloExportSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class YoloInstanceSegmentationExportManifest:
    dataset_version_id: str; format_id: str = yolo_seg
    category_names: tuple[str, ...] = (); splits: tuple[YoloExportSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class YoloPoseExportManifest:
    dataset_version_id: str; format_id: str = yolo_pose
    category_names: tuple[str, ...] = (); splits: tuple[YoloExportSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
