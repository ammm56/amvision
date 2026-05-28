"""COCO keypoints 数据集导出定义。"""

from __future__ import annotations
from dataclasses import dataclass, field

COCO_KEYPOINTS_DATASET_FORMAT = "coco-keypoints-v1"

@dataclass(frozen=True)
class CocoKeypointsCategory:
    category_id: int; name: str; supercategory: str = "object"; keypoints: tuple[str, ...] = (); skeleton: tuple[tuple[int, int], ...] = ()

@dataclass(frozen=True)
class CocoKeypointsImage:
    image_id: int; file_name: str; width: int; height: int

@dataclass(frozen=True)
class CocoKeypointsAnnotation:
    annotation_id: int; image_id: int; category_id: int; bbox_xywh: tuple[float, float, float, float]
    keypoints: list[float] | None = None; num_keypoints: int = 0
    area: float | None = None; iscrowd: int = 0

@dataclass(frozen=True)
class CocoKeypointsAnnotationPayload(CocoKeypointsAnnotation):
    pass

@dataclass(frozen=True)
class CocoKeypointsSplit:
    name: str; image_root: str; annotation_file: str; sample_count: int

@dataclass(frozen=True)
class CocoKeypointsExportManifest:
    dataset_version_id: str; format_id: str = COCO_KEYPOINTS_DATASET_FORMAT
    category_names: tuple[str, ...] = (); splits: tuple[CocoKeypointsSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
