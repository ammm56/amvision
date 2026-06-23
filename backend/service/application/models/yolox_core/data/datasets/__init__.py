"""YOLOX detection 数据集入口。"""

from .coco import (
    CocoDetectionExportDataset,
    ResolvedCocoSample,
    ResolvedCocoSplit,
    load_coco_ground_truth_silently,
    resolve_coco_splits,
    resolve_train_split,
    resolve_validation_split,
)
from .detection import (
    YoloXDetectionDataset,
    YoloXDetectionSplit,
    build_yolox_detection_dataset,
    get_yolox_detection_evaluation_annotation_file,
    resolve_yolox_detection_splits,
)
from .voc import (
    ParsedVocAnnotation,
    ParsedVocObject,
    ResolvedVocSample,
    ResolvedVocSplit,
    VocDetectionExportDataset,
    parse_voc_annotation_file,
    read_voc_annotation_objects,
    resolve_voc_splits,
)

__all__ = [
    "CocoDetectionExportDataset",
    "ParsedVocAnnotation",
    "ParsedVocObject",
    "ResolvedCocoSample",
    "ResolvedCocoSplit",
    "ResolvedVocSample",
    "ResolvedVocSplit",
    "VocDetectionExportDataset",
    "YoloXDetectionDataset",
    "YoloXDetectionSplit",
    "build_yolox_detection_dataset",
    "get_yolox_detection_evaluation_annotation_file",
    "load_coco_ground_truth_silently",
    "parse_voc_annotation_file",
    "read_voc_annotation_objects",
    "resolve_coco_splits",
    "resolve_train_split",
    "resolve_validation_split",
    "resolve_voc_splits",
    "resolve_yolox_detection_splits",
]
