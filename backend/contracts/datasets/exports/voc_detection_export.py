"""VOC detection 数据集导出定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


# VOC detection 数据集导出格式 id。
VOC_DETECTION_DATASET_FORMAT = "voc-detection-v1"


@dataclass(frozen=True)
class VocDetectionSplit:
    """描述 VOC detection 导出的单个 split。

    字段：
    - name：split 名称。
    - image_root：导出图片根目录。
    - annotation_root：导出标注根目录。
    - image_set_file：split 对应的 image set 文件路径。
    - sample_count：split 中的样本数量。
    """

    name: str
    image_root: str
    annotation_root: str
    image_set_file: str
    sample_count: int


@dataclass(frozen=True)
class VocDetectionObject:
    """描述 VOC detection XML 中的单个目标对象。

    字段：
    - category_name：类别名称。
    - bbox_xyxy：检测框坐标，格式为 xyxy。
    - difficult：是否为 difficult 标记。
    - truncated：是否为 truncated 标记。
    - pose：目标姿态描述。
    """

    category_name: str
    bbox_xyxy: tuple[int, int, int, int]
    difficult: int = 0
    truncated: int = 0
    pose: str = "Unspecified"


@dataclass(frozen=True)
class VocDetectionDocument:
    """描述单张图片对应的 VOC detection XML 文档。"""

    sample_id: str
    image_id: int
    split_name: str
    file_name: str
    image_relative_path: str
    annotation_relative_path: str
    width: int
    height: int
    objects: tuple[VocDetectionObject, ...]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VocDetectionAnnotationPayload:
    """描述单个 split 的 VOC detection annotation payload。"""

    split_name: str
    documents: tuple[VocDetectionDocument, ...]
    category_names: tuple[str, ...]
    info: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VocDetectionExportManifest:
    """描述 VOC detection 数据集导出的 manifest。"""

    format_id: str
    dataset_version_id: str
    category_names: tuple[str, ...]
    splits: tuple[VocDetectionSplit, ...]
    metadata: dict[str, object] = field(default_factory=dict)