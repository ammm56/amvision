"""YOLOv8 detection 数据层值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class YoloV8DetectionResolvedSplit:
    """描述一个已经解析完成的 YOLOv8 detection split。"""

    name: str
    image_root: Path
    sample_count: int
    annotation_payload: dict[str, object]
    annotation_file: Path | None = None


@dataclass(frozen=True)
class YoloV8DetectionTrainingAnnotation:
    """描述 YOLOv8 detection 单个训练目标的原图 bbox 与类别。"""

    category_index: int
    category_id: int
    bbox_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class YoloV8DetectionTrainingSample:
    """描述 YOLOv8 detection 一张训练图片和完整检测标注。"""

    image_id: int
    image_path: Path
    image_width: int
    image_height: int
    annotations: tuple[YoloV8DetectionTrainingAnnotation, ...]


@dataclass(frozen=True)
class YoloV8DetectionPreparedTarget:
    """描述 YOLOv8 detection 单张图片在当前输入尺寸下的训练目标。"""

    image_id: int
    image_width: int
    image_height: int
    boxes_xyxy: tuple[tuple[float, float, float, float], ...]
    category_indexes: tuple[int, ...]


@dataclass(frozen=True)
class YoloV8DetectionAugmentationOptions:
    """描述 YOLOv8 detection 训练阶段启用的数据增强参数。"""

    flip_prob: float
    hsv_prob: float
    mosaic_prob: float
    mixup_prob: float
    enable_mixup: bool
    affine_prob: float
    degrees: float
    translate: float
    scale: float
    shear: float
    perspective: float
    mosaic_scale: tuple[float, float]
    mixup_scale: tuple[float, float]
    close_mosaic_epochs: int
    multi_scale: bool
    multi_scale_range: tuple[float, float]
    multi_scale_stride: int


__all__ = [
    "YoloV8DetectionAugmentationOptions",
    "YoloV8DetectionPreparedTarget",
    "YoloV8DetectionResolvedSplit",
    "YoloV8DetectionTrainingAnnotation",
    "YoloV8DetectionTrainingSample",
]
