"""数据集导出请求、结果和任务对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.contracts.datasets.exports.coco_detection_export import (
    COCO_DETECTION_DATASET_FORMAT,
    CocoDetectionAnnotationPayload,
    CocoDetectionExportManifest,
)
from backend.contracts.datasets.exports.coco_instance_segmentation_export import (
    CocoInstanceSegmentationExportManifest,
)
from backend.contracts.datasets.exports.coco_keypoints_export import (
    CocoKeypointsExportManifest,
)
from backend.contracts.datasets.exports.dataset_formats import DatasetExportFormatId
from backend.contracts.datasets.exports.dota_obb_export import (
    DotaObbAnnotationPayload,
    DotaObbExportManifest,
)
from backend.contracts.datasets.exports.imagenet_classification_export import (
    ImageNetClassificationAnnotationPayload,
    ImageNetClassificationExportManifest,
)
from backend.contracts.datasets.exports.voc_detection_export import (
    VocDetectionAnnotationPayload,
    VocDetectionExportManifest,
)
from backend.contracts.datasets.exports.yolo_export import (
    YoloDetectionExportManifest,
    YoloInstanceSegmentationExportManifest,
    YoloPoseExportManifest,
)


DatasetExportFormatManifest = (
    CocoDetectionExportManifest
    | VocDetectionExportManifest
    | ImageNetClassificationExportManifest
    | DotaObbExportManifest
    | YoloDetectionExportManifest
    | YoloInstanceSegmentationExportManifest
    | YoloPoseExportManifest
    | CocoInstanceSegmentationExportManifest
    | CocoKeypointsExportManifest
)
DatasetExportAnnotationPayload = (
    CocoDetectionAnnotationPayload
    | VocDetectionAnnotationPayload
    | ImageNetClassificationAnnotationPayload
    | DotaObbAnnotationPayload
)


@dataclass(frozen=True)
class DatasetExportRequest:
    """描述一次数据集导出请求。

    字段：
    - project_id：所属项目 id。
    - dataset_id：数据集 id。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - format_id：目标导出格式 id。
    - output_object_prefix：导出目录前缀。
    - category_names：导出时使用的类别名列表。
    - include_test_split：是否包含 test split。
    - dataset_export_id：显式指定的导出记录 id；为空时按导出方式自动生成。
    """

    project_id: str
    dataset_id: str
    dataset_version_id: str
    format_id: DatasetExportFormatId = COCO_DETECTION_DATASET_FORMAT
    output_object_prefix: str = ""
    category_names: tuple[str, ...] = ()
    include_test_split: bool = True
    dataset_export_id: str | None = None


@dataclass(frozen=True)
class DatasetExportResult:
    """描述数据集导出的结果。"""

    dataset_version_id: str
    format_id: str
    manifest_object_key: str
    split_names: tuple[str, ...]
    sample_count: int
    category_names: tuple[str, ...] = ()
    dataset_export_id: str | None = None
    export_path: str | None = None
    format_manifest: DatasetExportFormatManifest | None = None
    annotation_payloads_by_split: dict[str, DatasetExportAnnotationPayload] = field(
        default_factory=dict
    )
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetExportArtifact:
    """描述训练前数据集导出生成的 export file 边界。"""

    dataset_export_id: str | None
    dataset_id: str
    dataset_version_id: str
    format_id: str
    manifest_object_key: str
    export_path: str | None
    split_names: tuple[str, ...]
    sample_count: int
    category_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class DatasetExportTaskSubmission:
    """描述一次 DatasetExport 任务提交结果。"""

    dataset_export_id: str
    task_id: str
    queue_name: str
    queue_task_id: str
    dataset_version_id: str
    format_id: str
    status: str


@dataclass(frozen=True)
class DatasetExportTaskResult:
    """描述一次 DatasetExport 后台任务执行结果。"""

    task_id: str
    status: str
    artifact: DatasetExportArtifact


class DatasetExporter(Protocol):
    """把 DatasetVersion 导出为指定格式数据集的接口。"""

    def export_dataset(self, request: DatasetExportRequest) -> DatasetExportResult:
        """执行数据集导出。"""

        ...
