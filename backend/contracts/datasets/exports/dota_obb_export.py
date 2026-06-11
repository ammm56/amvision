"""DOTA 风格 OBB 数据集导出定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts.datasets.exports.dataset_formats import DOTA_OBB_DATASET_FORMAT


@dataclass(frozen=True)
class DotaObbSplit:
    """描述 DOTA 风格 OBB 导出的单个 split。"""

    name: str
    image_root: str
    annotation_file: str
    sample_count: int


@dataclass(frozen=True)
class DotaObbCategory:
    """描述 OBB 导出中的类别对象。"""

    category_id: int
    name: str


@dataclass(frozen=True)
class DotaObbImage:
    """描述 OBB 导出中的图片对象。"""

    image_id: int
    file_name: str
    width: int
    height: int


@dataclass(frozen=True)
class DotaObbAnnotation:
    """描述 OBB 导出中的单个标注对象。"""

    annotation_id: int
    image_id: int
    category_id: int
    bbox_xywh: tuple[float, float, float, float]
    polygon_xy: tuple[float, ...]
    area: float
    iscrowd: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DotaObbAnnotationPayload:
    """描述单个 split 的 OBB annotation payload。"""

    split_name: str
    images: tuple[DotaObbImage, ...]
    annotations: tuple[DotaObbAnnotation, ...]
    categories: tuple[DotaObbCategory, ...]
    info: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DotaObbExportManifest:
    """描述 DOTA 风格 OBB 数据集导出的 manifest。"""

    dataset_version_id: str
    format_id: str = DOTA_OBB_DATASET_FORMAT
    category_names: tuple[str, ...] = ()
    splits: tuple[DotaObbSplit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
