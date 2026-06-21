"""数据集导出接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import uuid4
from typing import Protocol

from backend.queue import QueueBackend
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
from backend.contracts.datasets.exports.dataset_formats import (
    DatasetExportFormatId,
    IMPLEMENTED_DATASET_EXPORT_FORMATS,
    SUPPORTED_DATASET_EXPORT_FORMATS,
)
from backend.contracts.datasets.exports.dota_obb_export import (
    DotaObbAnnotationPayload,
    DotaObbExportManifest,
)
from backend.contracts.datasets.exports.imagenet_classification_export import (
    ImageNetClassificationAnnotationPayload,
    ImageNetClassificationExportManifest,
)
from backend.contracts.datasets.exports.yolo_export import (
    YoloDetectionExportManifest,
    YoloInstanceSegmentationExportManifest,
    YoloPoseExportManifest,
)
from backend.contracts.datasets.exports.voc_detection_export import (
    VocDetectionAnnotationPayload,
    VocDetectionExportManifest,
)
from backend.service.application.datasets.exports.formats.common import (
    _dataset_export_format_matches_task_type,
)
from backend.service.application.datasets.exports.formats.files import (
    DatasetExportFileWriterMixin,
)
from backend.service.application.datasets.exports.formats.payloads import (
    DatasetExportPayloadBuilderMixin,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
)
from backend.service.domain.tasks.task_records import TaskEvent, TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


DATASET_EXPORT_TASK_KIND = "dataset-export"
DATASET_EXPORT_QUEUE_NAME = "dataset-exports"


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
    """描述数据集导出的结果。

    字段：
    - dataset_version_id：导出来源的 DatasetVersion id。
    - format_id：实际使用的导出格式 id。
    - manifest_object_key：导出 manifest 的 object key。
    - split_names：导出的 split 名称列表。
    - sample_count：导出的样本总数。
    - category_names：导出时使用的类别名列表。
    - dataset_export_id：导出记录 id；只有正式落盘时才会生成。
    - export_path：导出根目录 object key。
    - format_manifest：格式级 manifest。
    - annotation_payloads_by_split：按 split 保存的 annotation payload。
    - metadata：附加元数据。
    """

    dataset_version_id: str
    format_id: str
    manifest_object_key: str
    split_names: tuple[str, ...]
    sample_count: int
    category_names: tuple[str, ...] = ()
    dataset_export_id: str | None = None
    export_path: str | None = None
    format_manifest: DatasetExportFormatManifest | None = None
    annotation_payloads_by_split: dict[str, DatasetExportAnnotationPayload] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetExportArtifact:
    """描述训练前数据集导出生成的 export file 边界。

    字段：
    - dataset_export_id：导出记录 id；未显式落盘时为空。
    - dataset_id：来源 Dataset id。
    - dataset_version_id：来源 DatasetVersion id。
    - format_id：导出格式 id。
    - manifest_object_key：训练和评估应消费的 manifest 文件 object key。
    - export_path：导出根目录 object key。
    - split_names：导出包含的 split 列表。
    - sample_count：导出样本总数。
    - category_names：导出类别名列表。
    """

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
    """描述一次 DatasetExport 任务提交结果。

    字段：
    - dataset_export_id：正式 DatasetExport 资源 id。
    - task_id：正式 TaskRecord id。
    - queue_name：提交到的队列名称。
    - queue_task_id：本地持久化队列消息 id。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - format_id：目标导出格式 id。
    - status：导出资源当前状态。
    """

    dataset_export_id: str
    task_id: str
    queue_name: str
    queue_task_id: str
    dataset_version_id: str
    format_id: str
    status: str


@dataclass(frozen=True)
class DatasetExportTaskResult:
    """描述一次 DatasetExport 后台任务执行结果。

    字段：
    - task_id：处理的任务 id。
    - status：任务最终状态。
    - artifact：供 training 消费的唯一 export file 边界。
    """

    task_id: str
    status: str
    artifact: DatasetExportArtifact


class DatasetExporter(Protocol):
    """把 DatasetVersion 导出为指定格式数据集的接口。"""

    def export_dataset(self, request: DatasetExportRequest) -> DatasetExportResult:
        """执行数据集导出。

        参数：
        - request：数据集导出请求。

        返回：
        - 数据集导出结果。
        """

        ...


class SqlAlchemyDatasetExporter(
    DatasetExportPayloadBuilderMixin,
    DatasetExportFileWriterMixin,
):
    """使用 SQLAlchemy Repository 与 Unit of Work 实现数据集导出。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
    ) -> None:
        """初始化基于 SQLAlchemy 的数据集导出器。

        参数：
        - session_factory：用于创建请求级数据库会话的工厂。
        - dataset_storage：可选的本地数据集文件存储服务；提供时会把导出结果正式写盘。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def export_dataset(self, request: DatasetExportRequest) -> DatasetExportResult:
        """执行数据集导出。

        参数：
        - request：数据集导出请求。

        返回：
        - 数据集导出结果。
        """

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_version = unit_of_work.datasets.get_dataset_version(request.dataset_version_id)
        finally:
            unit_of_work.close()

        return self._export_loaded_dataset(request=request, dataset_version=dataset_version)

    def _export_loaded_dataset(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion | None,
    ) -> DatasetExportResult:
        """基于已读取的 DatasetVersion 构建导出结果。

        参数：
        - request：数据集导出请求。
        - dataset_version：已读取的 DatasetVersion。

        返回：
        - 数据集导出结果。
        """

        if dataset_version is None:
            raise ValueError(f"未知的 DatasetVersion: {request.dataset_version_id}")
        if dataset_version.project_id != request.project_id:
            raise ValueError("请求中的 project_id 与 DatasetVersion 不一致")
        if dataset_version.dataset_id != request.dataset_id:
            raise ValueError("请求中的 dataset_id 与 DatasetVersion 不一致")
        if request.format_id not in SUPPORTED_DATASET_EXPORT_FORMATS:
            raise ValueError(f"未知的导出格式: {request.format_id}")
        if request.format_id not in IMPLEMENTED_DATASET_EXPORT_FORMATS:
            raise NotImplementedError(
                f"当前最小实现只落了 {IMPLEMENTED_DATASET_EXPORT_FORMATS}，其他格式已在支持列表中预留"
            )
        if not _dataset_export_format_matches_task_type(
            format_id=request.format_id,
            task_type=dataset_version.task_type,
        ):
            raise ValueError(
                f"导出格式 {request.format_id} 与 task_type={dataset_version.task_type} 不匹配"
            )

        category_names = self._resolve_category_names(
            categories=dataset_version.categories,
            category_names=request.category_names,
        )
        dataset_export_id = request.dataset_export_id
        if dataset_export_id is None and self.dataset_storage is not None and not request.output_object_prefix:
            dataset_export_id = self._next_id("dataset-export")
        export_prefix = self._resolve_export_prefix(
            request=request,
            dataset_export_id=dataset_export_id,
        )
        split_samples = self._collect_split_samples(
            dataset_version=dataset_version,
            include_test_split=request.include_test_split,
        )
        class_map = self._build_class_map(dataset_version.categories)
        exported_at = datetime.now(timezone.utc).isoformat()
        format_manifest, annotation_payloads_by_split = self._build_format_payloads(
            request=request,
            dataset_version=dataset_version,
            split_samples=split_samples,
            category_names=category_names,
            class_map=class_map,
            export_prefix=export_prefix,
            exported_at=exported_at,
        )

        export_result = DatasetExportResult(
            dataset_version_id=request.dataset_version_id,
            format_id=request.format_id,
            manifest_object_key=f"{export_prefix}/manifest.json",
            split_names=tuple(split_name for split_name, _ in split_samples),
            sample_count=sum(len(samples) for _, samples in split_samples),
            category_names=category_names,
            dataset_export_id=dataset_export_id,
            export_path=export_prefix,
            format_manifest=format_manifest,
            annotation_payloads_by_split=annotation_payloads_by_split,
            metadata={
                "source_dataset_id": dataset_version.dataset_id,
                "target_format": request.format_id,
                "class_map": class_map,
                "exported_at": exported_at,
                "export_path": export_prefix,
                "implemented_formats": IMPLEMENTED_DATASET_EXPORT_FORMATS,
            },
        )

        if self.dataset_storage is not None:
            self._write_export_files(
                dataset_version=dataset_version,
                split_samples=split_samples,
                export_result=export_result,
            )

        return export_result

    def _resolve_category_names(
        self,
        *,
        categories: tuple[DatasetCategory, ...],
        category_names: tuple[str, ...],
    ) -> tuple[str, ...]:
        """确定导出时使用的类别名列表。

        参数：
        - categories：DatasetVersion 中的类别列表。
        - category_names：请求中显式传入的类别名列表。

        返回：
        - 导出时使用的类别名列表。
        """

        if category_names:
            return category_names

        return tuple(category.name for category in sorted(categories, key=lambda item: item.category_id))

    def _resolve_export_prefix(
        self,
        *,
        request: DatasetExportRequest,
        dataset_export_id: str | None,
    ) -> str:
        """确定数据集导出的输出路径前缀。

        参数：
        - request：数据集导出请求。
        返回：
        - 导出路径前缀。
        """

        if request.output_object_prefix:
            return request.output_object_prefix.rstrip("/")

        if dataset_export_id is not None:
            return (
                f"projects/{request.project_id}/datasets/{request.dataset_id}/exports/"
                f"{dataset_export_id}"
            )

        return f"exports/{request.dataset_version_id}/{request.format_id}"























    def _build_version_image_relative_path(
        self,
        *,
        dataset_version: DatasetVersion,
        sample: DatasetSample,
    ) -> str:
        """计算 DatasetVersion 中某张图片的相对路径。"""

        image_object_key = str(
            sample.metadata.get("image_object_key") or f"images/{sample.split}/{sample.file_name}"
        ).lstrip("/")
        return (
            f"projects/{dataset_version.project_id}/datasets/{dataset_version.dataset_id}/versions/"
            f"{dataset_version.dataset_version_id}/{image_object_key}"
        )

    def _next_id(self, prefix: str) -> str:
        """生成一个带前缀的新对象 id。"""

        return f"{prefix}-{uuid4().hex[:12]}"


class SqlAlchemyDatasetExportTaskService:
    """把 DatasetExport 接入任务系统的应用服务。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend | None = None,
    ) -> None:
        """初始化 DatasetExport 任务服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        - queue_backend：可选的任务队列后端；提交任务时必填。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory)
        self.exporter = SqlAlchemyDatasetExporter(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    def submit_export_task(
        self,
        request: DatasetExportRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> DatasetExportTaskSubmission:
        """创建并入队一条 DatasetExport 任务。

        参数：
        - request：导出请求。
        - created_by：提交主体 id。
        - display_name：可选的展示名称。

        返回：
        - 任务提交结果。
        """

        self._validate_submission_request(request)
        queue_backend = self._require_queue_backend()
        dataset_version = self._require_dataset_version(request.dataset_version_id)
        self._validate_dataset_version_identity(
            request=request,
            dataset_version=dataset_version,
        )
        created_at = self._now_iso()
        task_id = self._next_id("task")
        dataset_export_id = request.dataset_export_id or self._next_id("dataset-export")
        task_record = self._build_task_record(
            request=request,
            task_id=task_id,
            dataset_export_id=dataset_export_id,
            created_at=created_at,
            created_by=created_by,
            display_name=display_name,
        )
        created_event = TaskEvent(
            event_id=self._next_id("task-event"),
            task_id=task_id,
            event_type="status",
            created_at=created_at,
            message="task created",
            payload={"state": "queued"},
        )
        dataset_export = DatasetExport(
            dataset_export_id=dataset_export_id,
            dataset_id=request.dataset_id,
            project_id=request.project_id,
            dataset_version_id=request.dataset_version_id,
            format_id=request.format_id,
            task_type=dataset_version.task_type,
            status="queued",
            created_at=created_at,
            task_id=task_id,
            include_test_split=request.include_test_split,
            category_names=request.category_names,
            metadata={
                "output_object_prefix": request.output_object_prefix,
                "created_by": created_by,
                "target_format": request.format_id,
            },
        )
        self._save_dataset_export_and_task(
            dataset_export=dataset_export,
            task_record=task_record,
            created_event=created_event,
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=DATASET_EXPORT_QUEUE_NAME,
                payload={"dataset_export_id": dataset_export_id},
                metadata={
                    "dataset_export_id": dataset_export_id,
                    "task_id": task_id,
                    "project_id": request.project_id,
                    "dataset_id": request.dataset_id,
                    "dataset_version_id": request.dataset_version_id,
                    "format_id": request.format_id,
                },
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="dataset export queue submission failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "error_message": str(error),
                        "progress": {"stage": "failed"},
                    },
                )
            )
            self._save_dataset_export(
                replace(
                    dataset_export,
                    status="failed",
                    error_message=str(error),
                )
            )
            raise

        self._save_dataset_export(
            replace(
                dataset_export,
                metadata={
                    **dataset_export.metadata,
                    "queue_name": queue_task.queue_name,
                    "queue_task_id": queue_task.task_id,
                },
            )
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="dataset export queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return DatasetExportTaskSubmission(
            dataset_export_id=dataset_export_id,
            task_id=task_id,
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_version_id=request.dataset_version_id,
            format_id=request.format_id,
            status="queued",
        )

    def process_export_task(self, dataset_export_id: str) -> DatasetExportTaskResult:
        """执行一条已入队的 DatasetExport 任务。

        参数：
        - dataset_export_id：要处理的 DatasetExport 资源 id。

        返回：
        - 导出任务执行结果。
        """

        dataset_export = self._require_dataset_export(dataset_export_id)
        task_id = self._require_task_id(dataset_export)

        existing_artifact = self._build_export_artifact_from_dataset_export(dataset_export)
        if dataset_export.status == "completed" and existing_artifact is not None:
            return DatasetExportTaskResult(
                task_id=task_id,
                status="succeeded",
                artifact=existing_artifact,
            )
        if dataset_export.status == "running":
            raise InvalidRequestError(
                "当前导出任务正在执行，不能重复执行",
                details={"dataset_export_id": dataset_export_id},
            )
        if dataset_export.status == "failed":
            raise InvalidRequestError(
                "当前导出任务已经结束，不能重复执行",
                details={"dataset_export_id": dataset_export_id, "state": dataset_export.status},
            )

        export_request = self._build_export_request_from_dataset_export(dataset_export)
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="dataset export started",
                payload={
                    "state": "running",
                    "started_at": self._now_iso(),
                    "progress": {
                        "stage": "exporting",
                        "percent": 10,
                    },
                },
            )
        )
        self._save_dataset_export(
            replace(
                dataset_export,
                status="running",
                error_message=None,
            )
        )

        try:
            export_result = self.exporter.export_dataset(export_request)
        except Exception as error:
            self._save_dataset_export(
                replace(
                    self._require_dataset_export(dataset_export_id),
                    status="failed",
                    error_message=str(error),
                )
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="dataset export failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "error_message": str(error),
                        "progress": {"stage": "failed"},
                        "result": {
                            "dataset_version_id": export_request.dataset_version_id,
                            "format_id": export_request.format_id,
                        },
                    },
                )
            )
            raise

        artifact = self._build_export_artifact(
            request=export_request,
            export_result=export_result,
        )
        self._save_dataset_export(
            replace(
                self._require_dataset_export(dataset_export_id),
                status="completed",
                export_path=artifact.export_path,
                manifest_object_key=artifact.manifest_object_key,
                split_names=artifact.split_names,
                sample_count=artifact.sample_count,
                category_names=artifact.category_names,
                error_message=None,
                metadata={
                    **dataset_export.metadata,
                    **export_result.metadata,
                },
            )
        )
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="dataset export completed",
                payload={
                    "state": "succeeded",
                    "finished_at": self._now_iso(),
                    "progress": {
                        "stage": "completed",
                        "percent": 100,
                        "sample_count": artifact.sample_count,
                        "category_count": len(artifact.category_names),
                    },
                    "result": self._serialize_export_artifact(artifact),
                },
            )
        )
        return DatasetExportTaskResult(
            task_id=task_id,
            status="succeeded",
            artifact=artifact,
        )

    def _validate_submission_request(self, request: DatasetExportRequest) -> None:
        """校验导出任务提交请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.dataset_id.strip():
            raise InvalidRequestError("dataset_id 不能为空")
        if not request.dataset_version_id.strip():
            raise InvalidRequestError("dataset_version_id 不能为空")
        if request.format_id not in SUPPORTED_DATASET_EXPORT_FORMATS:
            raise InvalidRequestError(
                "当前导出格式不受支持",
                details={"format_id": request.format_id},
            )
        if request.format_id not in IMPLEMENTED_DATASET_EXPORT_FORMATS:
            raise InvalidRequestError(
                "当前导出格式尚未实现",
                details={
                    "format_id": request.format_id,
                    "implemented_formats": IMPLEMENTED_DATASET_EXPORT_FORMATS,
                },
            )

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交导出任务时缺少 queue backend")

        return self.queue_backend

    def _build_task_spec(
        self,
        request: DatasetExportRequest,
        *,
        dataset_export_id: str,
    ) -> dict[str, object]:
        """把导出请求转换为 TaskRecord 使用的任务规格。"""

        return {
            "dataset_export_id": dataset_export_id,
            "dataset_id": request.dataset_id,
            "dataset_version_id": request.dataset_version_id,
            "format_id": request.format_id,
            "output_object_prefix": request.output_object_prefix,
            "category_names": list(request.category_names),
            "include_test_split": request.include_test_split,
        }

    def _build_task_record(
        self,
        *,
        request: DatasetExportRequest,
        task_id: str,
        dataset_export_id: str,
        created_at: str,
        created_by: str | None,
        display_name: str,
    ) -> TaskRecord:
        """构建与 DatasetExport 资源绑定的 TaskRecord。"""

        return TaskRecord(
            task_id=task_id,
            task_kind=DATASET_EXPORT_TASK_KIND,
            project_id=request.project_id,
            display_name=display_name.strip()
            or f"dataset export {request.dataset_version_id} -> {request.format_id}",
            created_by=created_by,
            created_at=created_at,
            task_spec=self._build_task_spec(request, dataset_export_id=dataset_export_id),
            worker_pool=DATASET_EXPORT_TASK_KIND,
            metadata={
                "dataset_export_id": dataset_export_id,
                "dataset_id": request.dataset_id,
                "dataset_version_id": request.dataset_version_id,
                "target_format": request.format_id,
            },
            state="queued",
        )

    def _save_dataset_export_and_task(
        self,
        *,
        dataset_export: DatasetExport,
        task_record: TaskRecord,
        created_event: TaskEvent,
    ) -> None:
        """把 DatasetExport 与 TaskRecord 一起落盘。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            unit_of_work.dataset_exports.save_dataset_export(dataset_export)
            unit_of_work.tasks.save_task(task_record)
            unit_of_work.tasks.save_task_event(created_event)
            unit_of_work.commit()
        finally:
            unit_of_work.close()

    def _require_dataset_version(self, dataset_version_id: str) -> DatasetVersion:
        """按 id 读取导出来源的 DatasetVersion。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_version = unit_of_work.datasets.get_dataset_version(dataset_version_id)
        finally:
            unit_of_work.close()

        if dataset_version is None:
            raise ResourceNotFoundError(
                "找不到指定的 DatasetVersion",
                details={"dataset_version_id": dataset_version_id},
            )

        return dataset_version

    def _validate_dataset_version_identity(
        self,
        *,
        request: DatasetExportRequest,
        dataset_version: DatasetVersion,
    ) -> None:
        """校验导出请求与 DatasetVersion 身份是否一致。"""

        if dataset_version.project_id != request.project_id:
            raise InvalidRequestError(
                "请求中的 project_id 与 DatasetVersion 不一致",
                details={"dataset_version_id": dataset_version.dataset_version_id},
            )
        if dataset_version.dataset_id != request.dataset_id:
            raise InvalidRequestError(
                "请求中的 dataset_id 与 DatasetVersion 不一致",
                details={"dataset_version_id": dataset_version.dataset_version_id},
            )
        if not _dataset_export_format_matches_task_type(
            format_id=request.format_id,
            task_type=dataset_version.task_type,
        ):
            raise InvalidRequestError(
                "当前导出格式与 DatasetVersion.task_type 不匹配",
                details={
                    "dataset_version_id": dataset_version.dataset_version_id,
                    "format_id": request.format_id,
                    "task_type": dataset_version.task_type,
                },
            )

    def _require_dataset_export(self, dataset_export_id: str) -> DatasetExport:
        """按 id 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export(dataset_export_id)
        finally:
            unit_of_work.close()

        if dataset_export is None:
            raise ResourceNotFoundError(
                "找不到指定的 DatasetExport",
                details={"dataset_export_id": dataset_export_id},
            )

        return dataset_export

    def _save_dataset_export(self, dataset_export: DatasetExport) -> None:
        """保存一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            unit_of_work.dataset_exports.save_dataset_export(dataset_export)
            unit_of_work.commit()
        finally:
            unit_of_work.close()

    def _require_task_id(self, dataset_export: DatasetExport) -> str:
        """读取 DatasetExport 绑定的 task_id。"""

        if dataset_export.task_id is not None and dataset_export.task_id.strip():
            return dataset_export.task_id

        raise ServiceConfigurationError(
            "DatasetExport 缺少关联的 task_id",
            details={"dataset_export_id": dataset_export.dataset_export_id},
        )

    def _build_export_request_from_dataset_export(
        self,
        dataset_export: DatasetExport,
    ) -> DatasetExportRequest:
        """根据 DatasetExport 记录恢复导出请求。"""

        output_object_prefix = self._read_optional_str(dataset_export.metadata, "output_object_prefix") or ""
        category_names = dataset_export.category_names
        return DatasetExportRequest(
            project_id=dataset_export.project_id,
            dataset_id=dataset_export.dataset_id,
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            output_object_prefix=output_object_prefix,
            category_names=category_names,
            include_test_split=dataset_export.include_test_split,
            dataset_export_id=dataset_export.dataset_export_id,
        )

    def _build_export_artifact(
        self,
        *,
        request: DatasetExportRequest,
        export_result: DatasetExportResult,
    ) -> DatasetExportArtifact:
        """把导出结果转换为 training 消费的 export file 边界。"""

        return DatasetExportArtifact(
            dataset_export_id=export_result.dataset_export_id,
            dataset_id=request.dataset_id,
            dataset_version_id=export_result.dataset_version_id,
            format_id=export_result.format_id,
            manifest_object_key=export_result.manifest_object_key,
            export_path=export_result.export_path,
            split_names=export_result.split_names,
            sample_count=export_result.sample_count,
            category_names=export_result.category_names,
        )

    def _build_export_artifact_from_dataset_export(
        self,
        dataset_export: DatasetExport,
    ) -> DatasetExportArtifact | None:
        """从 DatasetExport 记录恢复 export artifact。"""

        if (
            dataset_export.manifest_object_key is None
            or not dataset_export.manifest_object_key.strip()
        ):
            return None

        return DatasetExportArtifact(
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_id=dataset_export.dataset_id,
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            manifest_object_key=dataset_export.manifest_object_key,
            export_path=dataset_export.export_path,
            split_names=dataset_export.split_names,
            sample_count=dataset_export.sample_count,
            category_names=dataset_export.category_names,
        )

    def _serialize_export_artifact(self, artifact: DatasetExportArtifact) -> dict[str, object]:
        """把 export artifact 转为可持久化的任务结果字典。"""

        return {
            "dataset_export_id": artifact.dataset_export_id,
            "dataset_id": artifact.dataset_id,
            "dataset_version_id": artifact.dataset_version_id,
            "format_id": artifact.format_id,
            "manifest_object_key": artifact.manifest_object_key,
            "export_path": artifact.export_path,
            "split_names": list(artifact.split_names),
            "sample_count": artifact.sample_count,
            "category_names": list(artifact.category_names),
        }

    def _read_required_str(self, payload: dict[str, object], key: str) -> str:
        """从字典中读取必填字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

        raise InvalidRequestError(
            "导出任务缺少必要字段",
            details={"field": key},
        )

    def _read_optional_str(self, payload: dict[str, object], key: str) -> str | None:
        """从字典中读取可选字符串字段。"""

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

        return None

    def _read_string_tuple(self, payload: dict[str, object], key: str) -> tuple[str, ...]:
        """从字典中读取字符串列表字段。"""

        value = payload.get(key)
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise InvalidRequestError(
                "导出任务字段类型不合法",
                details={"field": key},
            )

        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise InvalidRequestError(
                    "导出任务字段类型不合法",
                    details={"field": key},
                )
            items.append(item)
        return tuple(items)

    def _read_bool(self, payload: dict[str, object], key: str, *, default: bool) -> bool:
        """从字典中读取布尔字段。"""

        value = payload.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value

        raise InvalidRequestError(
            "导出任务字段类型不合法",
            details={"field": key},
        )

    def _read_int(self, payload: dict[str, object], key: str, *, default: int) -> int:
        """从字典中读取整数值。"""

        value = payload.get(key)
        if isinstance(value, int):
            return value

        return default

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 格式字符串。"""

        return datetime.now(timezone.utc).isoformat()

    def _next_id(self, prefix: str) -> str:
        """生成一个带前缀的新对象 id。"""

        return f"{prefix}-{uuid4().hex[:12]}"
