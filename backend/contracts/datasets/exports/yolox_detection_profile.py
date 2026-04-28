"""YOLOX detection 导出 profile 定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


# 默认的 YOLOX detection 导出 profile id。
YOLOX_DETECTION_EXPORT_PROFILE = "coco-detection-v1"


@dataclass(frozen=True)
class YoloXDetectionExportSplit:
    """描述 detection 导出中的单个 split。

    字段：
    - name：split 名称。
    - image_root：split 对应的图片根目录。
    - annotation_manifest：split 对应的标注 manifest 路径。
    - sample_count：split 中的样本数量。
    """

    name: str
    image_root: str
    annotation_manifest: str
    sample_count: int


@dataclass(frozen=True)
class YoloXDetectionExportManifest:
    """描述 YOLOX detection 导出结果的 manifest。

    字段：
    - profile_id：使用的导出 profile id。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - category_names：导出时使用的类别名列表。
    - splits：导出得到的 split 清单。
    - metadata：附加元数据。
    """

    profile_id: str
    dataset_version_id: str
    category_names: tuple[str, ...]
    splits: tuple[YoloXDetectionExportSplit, ...]
    metadata: dict[str, object] = field(default_factory=dict)