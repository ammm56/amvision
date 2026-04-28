"""最小 DatasetVersion 对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# 最小支持的数据集任务类型。
DatasetTaskFamily = Literal["detection", "instance-segmentation", "semantic-segmentation", "pose"]


# 最小支持的数据集 split 名称。
DatasetSplitName = Literal["train", "val", "test"]


@dataclass(frozen=True)
class DatasetCategory:
    """描述 DatasetVersion 中的单个类别。

    字段：
    - category_id：类别 id。
    - name：类别名称。
    """

    category_id: int
    name: str


@dataclass(frozen=True)
class DetectionAnnotation:
    """描述 detection 样本中的单个标注。

    字段：
    - annotation_id：标注 id。
    - category_id：类别 id。
    - bbox_xywh：检测框坐标，格式为 xywh。
    - iscrowd：是否为 crowd 标记。
    - area：标注面积。
    - metadata：附加元数据。
    """

    annotation_id: str
    category_id: int
    bbox_xywh: tuple[float, float, float, float]
    iscrowd: int = 0
    area: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetSample:
    """描述 DatasetVersion 中的单个样本。

    字段：
    - sample_id：样本 id。
    - image_id：图片 id。
    - file_name：图片文件名。
    - width：图片宽度。
    - height：图片高度。
    - split：样本所属 split。
    - annotations：样本中的 detection 标注列表。
    - metadata：附加元数据。
    """

    sample_id: str
    image_id: int
    file_name: str
    width: int
    height: int
    split: DatasetSplitName
    annotations: tuple[DetectionAnnotation, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetVersion:
    """描述导出链路要使用的最小 DatasetVersion。

    字段：
    - dataset_version_id：DatasetVersion id。
    - dataset_id：所属 Dataset id。
    - project_id：所属项目 id。
    - categories：类别列表。
    - samples：样本列表。
    - task_family：数据集任务类型。
    - metadata：附加元数据。
    """

    dataset_version_id: str
    dataset_id: str
    project_id: str
    categories: tuple[DatasetCategory, ...]
    samples: tuple[DatasetSample, ...]
    task_family: DatasetTaskFamily = "detection"
    metadata: dict[str, object] = field(default_factory=dict)