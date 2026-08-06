"""COCO keypoints 数据集导出定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

COCO_KEYPOINTS_DATASET_FORMAT = "coco-keypoints-v1"


@dataclass(frozen=True)
class CocoKeypointsCategory:
    """描述 COCO keypoints 类别。"""

    category_id: int
    name: str
    supercategory: str = "object"
    keypoints: tuple[str, ...] = ()
    skeleton: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class CocoKeypointsImage:
    """描述 COCO keypoints 图片。"""

    image_id: int
    file_name: str
    width: int
    height: int


@dataclass(frozen=True)
class CocoKeypointsAnnotation:
    """描述 COCO keypoints 标注。"""

    annotation_id: int
    image_id: int
    category_id: int
    bbox_xywh: tuple[float, float, float, float]
    keypoints: list[float] | None = None
    num_keypoints: int = 0
    area: float | None = None
    iscrowd: int = 0


@dataclass(frozen=True)
class CocoKeypointsAnnotationPayload(CocoKeypointsAnnotation):
    """描述可直接序列化的 COCO keypoints 标注。"""


@dataclass(frozen=True)
class CocoKeypointsSplit:
    """描述 COCO keypoints 导出 split。"""

    name: str
    image_root: str
    annotation_file: str
    sample_count: int


@dataclass(frozen=True)
class CocoKeypointsExportManifest:
    """描述 COCO keypoints 导出 manifest。"""

    dataset_version_id: str
    format_id: str = COCO_KEYPOINTS_DATASET_FORMAT
    category_names: tuple[str, ...] = ()
    splits: tuple[CocoKeypointsSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
