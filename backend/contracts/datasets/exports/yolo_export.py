"""YOLO detection 数据集导出定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from backend.contracts.datasets.dataset_formats import (
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_OBB_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)


@dataclass(frozen=True)
class YoloExportSplit:
    """描述 YOLO 导出 split。"""

    name: str
    image_root: str
    label_root: str
    sample_count: int


@dataclass(frozen=True)
class YoloDetectionExportManifest:
    """描述 YOLO detection 导出 manifest。"""

    dataset_version_id: str
    format_id: str = YOLO_DETECTION_DATASET_FORMAT
    category_names: tuple[str, ...] = ()
    splits: tuple[YoloExportSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloInstanceSegmentationExportManifest:
    """描述 YOLO instance segmentation 导出 manifest。"""

    dataset_version_id: str
    format_id: str = YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
    category_names: tuple[str, ...] = ()
    splits: tuple[YoloExportSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloPoseExportManifest:
    """描述 YOLO pose 导出 manifest。"""

    dataset_version_id: str
    format_id: str = YOLO_POSE_DATASET_FORMAT
    category_names: tuple[str, ...] = ()
    splits: tuple[YoloExportSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloObbExportSplit:
    """描述 YOLO OBB 导出 split 及平台训练索引。"""

    name: str
    image_root: str
    label_root: str
    annotation_file: str
    sample_count: int


@dataclass(frozen=True)
class YoloObbExportManifest:
    """描述 YOLO OBB 导出 manifest。"""

    dataset_version_id: str
    format_id: str = YOLO_OBB_DATASET_FORMAT
    category_names: tuple[str, ...] = ()
    splits: tuple[YoloObbExportSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
