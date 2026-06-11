"""ImageNet 风格 classification 数据集导出定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts.datasets.exports.dataset_formats import (
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
)


@dataclass(frozen=True)
class ImageNetClassificationSplit:
    """描述 ImageNet 风格 classification 导出的单个 split。"""

    name: str
    image_root: str
    annotation_file: str
    sample_count: int


@dataclass(frozen=True)
class ImageNetClassificationCategory:
    """描述 classification 导出中的类别对象。"""

    category_id: int
    name: str


@dataclass(frozen=True)
class ImageNetClassificationImage:
    """描述 classification 导出中的图片对象。"""

    image_id: int
    file_name: str
    width: int
    height: int


@dataclass(frozen=True)
class ImageNetClassificationAnnotation:
    """描述 classification 导出中的样本类别对象。"""

    annotation_id: int
    image_id: int
    category_id: int
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ImageNetClassificationAnnotationPayload:
    """描述单个 split 的 classification annotation payload。"""

    split_name: str
    images: tuple[ImageNetClassificationImage, ...]
    annotations: tuple[ImageNetClassificationAnnotation, ...]
    categories: tuple[ImageNetClassificationCategory, ...]
    info: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ImageNetClassificationExportManifest:
    """描述 ImageNet 风格 classification 数据集导出的 manifest。"""

    dataset_version_id: str
    format_id: str = IMAGENET_CLASSIFICATION_DATASET_FORMAT
    category_names: tuple[str, ...] = ()
    categories: tuple[ImageNetClassificationCategory, ...] = ()
    splits: tuple[ImageNetClassificationSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
