"""COCO instance segmentation 数据集导出定义。"""

from __future__ import annotations
from dataclasses import dataclass, field

COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT = "coco-instance-seg-v1"

@dataclass(frozen=True)
class CocoInstanceSegmentationCategory:
    category_id: int; name: str; supercategory: str = "object"

@dataclass(frozen=True)
class CocoInstanceSegmentationImage:
    image_id: int; file_name: str; width: int; height: int

@dataclass(frozen=True)
class CocoInstanceSegmentationAnnotation:
    annotation_id: int; image_id: int; category_id: int; bbox_xywh: tuple[float, float, float, float]
    segmentation: list[list[float]] | dict[str, object] | None = None
    area: float | None = None; iscrowd: int = 0

@dataclass(frozen=True)
class CocoInstanceSegmentationAnnotationPayload(CocoInstanceSegmentationAnnotation):
    pass

@dataclass(frozen=True)
class CocoInstanceSegmentationSplit:
    name: str; image_root: str; annotation_file: str; sample_count: int

@dataclass(frozen=True)
class CocoInstanceSegmentationExportManifest:
    dataset_version_id: str; format_id: str = COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT
    category_names: tuple[str, ...] = (); splits: tuple[CocoInstanceSegmentationSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
