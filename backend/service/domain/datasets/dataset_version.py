"""最小 DatasetVersion 对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# 最小支持的数据集任务类型。
DatasetTaskType = Literal["detection", "instance-segmentation", "semantic-segmentation", "pose", "classification", "obb"]


# 最小支持的数据集 split 名称。
DatasetSplitName = Literal["train", "val", "test"]


# 当前内部使用的标注类型名称。
DatasetAnnotationType = Literal[
    "detection",
    "instance-segmentation",
    "pose",
    "classification",
    "obb",
]


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
    """描述 detection 样本中的单个标注。"""

    annotation_id: str
    category_id: int
    bbox_xywh: tuple[float, float, float, float]
    iscrowd: int = 0
    area: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class InstanceSegmentationAnnotation:
    """描述 instance segmentation 样本中的单个标注。"""

    annotation_id: str
    category_id: int
    bbox_xywh: tuple[float, float, float, float]
    segmentation: list[list[float]] | None = None
    iscrowd: int = 0
    area: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PoseAnnotation:
    """描述 pose 样本中的单个标注。"""

    annotation_id: str
    category_id: int
    bbox_xywh: tuple[float, float, float, float]
    keypoints: list[float] | None = None
    num_keypoints: int = 0
    iscrowd: int = 0
    area: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassificationAnnotation:
    """描述 classification 样本中的单个标注。

    说明：
    - classification 没有 bbox，多数情况下每个样本只会有一条类别标注。
    """

    annotation_id: str
    category_id: int
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ObbAnnotation:
    """描述 obb 样本中的单个标注。"""

    annotation_id: str
    category_id: int
    bbox_xywh: tuple[float, float, float, float]
    polygon_xy: tuple[float, ...] | None = None
    iscrowd: int = 0
    area: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


DatasetAnnotation = (
    DetectionAnnotation
    | InstanceSegmentationAnnotation
    | PoseAnnotation
    | ClassificationAnnotation
    | ObbAnnotation
)


def get_dataset_annotation_type(annotation: DatasetAnnotation) -> DatasetAnnotationType:
    """返回当前标注对象的内部类型名称。"""

    if isinstance(annotation, ClassificationAnnotation):
        return "classification"
    if isinstance(annotation, ObbAnnotation):
        return "obb"
    if isinstance(annotation, InstanceSegmentationAnnotation):
        return "instance-segmentation"
    if isinstance(annotation, PoseAnnotation):
        return "pose"
    return "detection"


def clone_dataset_annotation(
    annotation: DatasetAnnotation,
    *,
    annotation_id: str,
    metadata_updates: dict[str, object] | None = None,
) -> DatasetAnnotation:
    """复制一条标注，并替换 annotation_id 与附加 metadata。"""

    merged_metadata = {
        **dict(annotation.metadata),
        **(metadata_updates or {}),
    }
    if isinstance(annotation, ClassificationAnnotation):
        return ClassificationAnnotation(
            annotation_id=annotation_id,
            category_id=annotation.category_id,
            metadata=merged_metadata,
        )
    if isinstance(annotation, ObbAnnotation):
        return ObbAnnotation(
            annotation_id=annotation_id,
            category_id=annotation.category_id,
            bbox_xywh=annotation.bbox_xywh,
            polygon_xy=annotation.polygon_xy,
            iscrowd=annotation.iscrowd,
            area=annotation.area,
            metadata=merged_metadata,
        )
    if isinstance(annotation, InstanceSegmentationAnnotation):
        return InstanceSegmentationAnnotation(
            annotation_id=annotation_id,
            category_id=annotation.category_id,
            bbox_xywh=annotation.bbox_xywh,
            segmentation=annotation.segmentation,
            iscrowd=annotation.iscrowd,
            area=annotation.area,
            metadata=merged_metadata,
        )
    if isinstance(annotation, PoseAnnotation):
        return PoseAnnotation(
            annotation_id=annotation_id,
            category_id=annotation.category_id,
            bbox_xywh=annotation.bbox_xywh,
            keypoints=annotation.keypoints,
            num_keypoints=annotation.num_keypoints,
            iscrowd=annotation.iscrowd,
            area=annotation.area,
            metadata=merged_metadata,
        )
    return DetectionAnnotation(
        annotation_id=annotation_id,
        category_id=annotation.category_id,
        bbox_xywh=annotation.bbox_xywh,
        iscrowd=annotation.iscrowd,
        area=annotation.area,
        metadata=merged_metadata,
    )


def serialize_dataset_annotation(annotation: DatasetAnnotation) -> dict[str, object]:
    """把内部标注对象序列化为稳定字典。"""

    payload: dict[str, object] = {
        "annotation_id": annotation.annotation_id,
        "annotation_type": get_dataset_annotation_type(annotation),
        "category_id": annotation.category_id,
        "metadata": dict(annotation.metadata),
    }
    if isinstance(annotation, ClassificationAnnotation):
        return payload

    payload["bbox_xywh"] = list(annotation.bbox_xywh)
    payload["iscrowd"] = annotation.iscrowd
    payload["area"] = annotation.area
    if isinstance(annotation, InstanceSegmentationAnnotation):
        payload["segmentation"] = annotation.segmentation
    elif isinstance(annotation, PoseAnnotation):
        payload["keypoints"] = annotation.keypoints
        payload["num_keypoints"] = annotation.num_keypoints
    elif isinstance(annotation, ObbAnnotation):
        payload["polygon_xy"] = list(annotation.polygon_xy) if annotation.polygon_xy is not None else None
    return payload


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
    - annotations：样本中的统一标注列表。
    - metadata：附加元数据。
    """

    sample_id: str
    image_id: int
    file_name: str
    width: int
    height: int
    split: DatasetSplitName
    annotations: tuple[DatasetAnnotation, ...] = ()
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
    - task_type：数据集任务类型。
    - metadata：附加元数据。
    """

    dataset_version_id: str
    dataset_id: str
    project_id: str
    categories: tuple[DatasetCategory, ...]
    samples: tuple[DatasetSample, ...]
    task_type: DatasetTaskType = "detection"
    metadata: dict[str, object] = field(default_factory=dict)
