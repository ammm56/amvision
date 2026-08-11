"""VOC instance segmentation 数据集导出定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts.datasets.dataset_formats import (
    VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT as VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.voc_detection_export import (
    VOC_DETECTION_COORDINATE_CONVENTION,
    VocDetectionObject,
)


@dataclass(frozen=True)
class VocInstanceSegmentationSplit:
    """描述 VOC instance segmentation 的一个 split。"""

    name: str
    image_root: str
    annotation_root: str
    class_mask_root: str
    object_mask_root: str
    image_set_file: str
    sample_count: int


@dataclass(frozen=True)
class VocInstanceSegmentationDocument:
    """描述一张图片的 XML 与两张 indexed mask 输出位置。"""

    sample_id: str
    image_id: int
    split_name: str
    file_name: str
    image_relative_path: str
    annotation_relative_path: str
    class_mask_relative_path: str
    object_mask_relative_path: str
    width: int
    height: int
    coordinate_convention: str
    objects: tuple[VocDetectionObject, ...]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VocInstanceSegmentationAnnotationPayload:
    """描述单个 split 的 VOC instance segmentation 文档集合。"""

    split_name: str
    documents: tuple[VocInstanceSegmentationDocument, ...]
    category_names: tuple[str, ...]
    category_index_map: dict[int, str]
    info: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VocInstanceSegmentationExportManifest:
    """描述 VOC instance segmentation 导出 manifest。"""

    format_id: str
    dataset_version_id: str
    coordinate_convention: str
    category_names: tuple[str, ...]
    category_index_map: dict[int, str]
    splits: tuple[VocInstanceSegmentationSplit, ...]
    metadata: dict[str, object] = field(default_factory=dict)


__all__ = [
    "VOC_DETECTION_COORDINATE_CONVENTION",
    "VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT",
    "VocInstanceSegmentationAnnotationPayload",
    "VocInstanceSegmentationDocument",
    "VocInstanceSegmentationExportManifest",
    "VocInstanceSegmentationSplit",
]
