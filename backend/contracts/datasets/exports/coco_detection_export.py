"""COCO detection 数据集导出定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


# COCO detection 数据集导出格式 id。
COCO_DETECTION_DATASET_FORMAT = "coco-detection-v1"


@dataclass(frozen=True)
class CocoDetectionSplit:
    """描述 COCO detection 导出的单个 split。

    字段：
    - name：split 名称。
    - image_root：split 对应的图片根目录。
    - annotation_file：split 对应的 annotation 文件路径。
    - sample_count：split 中的样本数量。
    """

    name: str
    image_root: str
    annotation_file: str
    sample_count: int


@dataclass(frozen=True)
class CocoCategory:
    """描述 COCO detection payload 中的类别。

    字段：
    - category_id：类别 id。
    - name：类别名称。
    - supercategory：上级类别名称。
    """

    category_id: int
    name: str
    supercategory: str = "object"


@dataclass(frozen=True)
class CocoImage:
    """描述 COCO detection payload 中的图片对象。

    字段：
    - image_id：图片 id。
    - file_name：图片文件名。
    - width：图片宽度。
    - height：图片高度。
    """

    image_id: int
    file_name: str
    width: int
    height: int


@dataclass(frozen=True)
class CocoDetectionAnnotation:
    """描述 COCO detection payload 中的标注对象。

    字段：
    - annotation_id：标注 id。
    - image_id：所属图片 id。
    - category_id：类别 id。
    - bbox_xywh：检测框坐标，格式为 xywh。
    - area：标注面积。
    - iscrowd：crowd 标记。
    """

    annotation_id: int
    image_id: int
    category_id: int
    bbox_xywh: tuple[float, float, float, float]
    area: float
    iscrowd: int = 0


@dataclass(frozen=True)
class CocoDetectionAnnotationPayload:
    """描述单个 split 的最小 COCO detection annotation payload。

    字段：
    - split_name：当前 payload 对应的 split 名称。
    - images：图片列表。
    - annotations：标注列表。
    - categories：类别列表。
    - info：补充信息。
    """

    split_name: str
    images: tuple[CocoImage, ...]
    annotations: tuple[CocoDetectionAnnotation, ...]
    categories: tuple[CocoCategory, ...]
    info: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CocoDetectionExportManifest:
    """描述 COCO detection 数据集导出的 manifest。

    字段：
    - format_id：导出格式 id。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - category_names：导出时使用的类别名列表。
    - splits：导出得到的 split 清单。
    - metadata：附加元数据。
    """

    format_id: str
    dataset_version_id: str
    category_names: tuple[str, ...]
    splits: tuple[CocoDetectionSplit, ...]
    metadata: dict[str, object] = field(default_factory=dict)