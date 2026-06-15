"""RF-DETR detection 训练任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.queue import QueueBackend
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.rfdetr_model_spec import (
    RFDETR_DEFAULT_DATASET_FORMAT,
    RFDETR_DETECTION_SCALES,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


RFDETR_TRAINING_TASK_KIND = "rfdetr-training"
RFDETR_TRAINING_QUEUE_NAME = "rfdetr-trainings"


@dataclass(frozen=True)
class RfdetrTrainingTaskRequest:
    """描述一次 RF-DETR detection 训练任务创建请求。"""

    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    warm_start_model_version_id: str | None = None
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RfdetrTrainingTaskSubmission:
    """描述一次 RF-DETR detection 训练任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str


class SqlAlchemyRfdetrTrainingTaskService:
    """基于本地队列和 TaskRecord 的 RF-DETR detection 训练任务服务。"""

    task_type = DETECTION_TASK_TYPE
    model_type = "rfdetr"
    training_task_kind = RFDETR_TRAINING_TASK_KIND
    training_queue_name = RFDETR_TRAINING_QUEUE_NAME

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        queue_backend: QueueBackend | None = None,
        dataset_storage=None,
    ) -> None:
        """初始化 RF-DETR detection 训练任务服务。"""

        del dataset_storage
        self.session_factory = session_factory
        self.queue_backend = queue_backend
        self.task_service = SqlAlchemyTaskService(session_factory=self.session_factory)

    def submit_training_task(
        self,
        request: RfdetrTrainingTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> RfdetrTrainingTaskSubmission:
        """创建并入队一条 RF-DETR detection 训练任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        dataset_export = self._resolve_dataset_export(request)
        task_spec = self._build_task_spec(request=request, dataset_export=dataset_export)
        metadata = {
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_id": dataset_export.dataset_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "model_type": self.model_type,
            "task_type": self.task_type,
            "output_model_name": request.output_model_name,
            "model_scale": request.model_scale,
            "queue_payload": dict(task_spec),
        }
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=self.training_task_kind,
                display_name=display_name.strip() or request.output_model_name,
                created_by=created_by,
                task_spec=task_spec,
                worker_pool=self.training_task_kind,
                metadata=metadata,
            )
        )
        queue_payload = {
            "task_id": created_task.task_id,
            "task_kind": self.training_task_kind,
            **dict(task_spec),
        }
        try:
            queue_task = queue_backend.enqueue(
                queue_name=self.training_queue_name,
                payload=queue_payload,
                metadata={
                    "project_id": request.project_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                    "model_type": self.model_type,
                },
            )
        except Exception as exc:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="status",
                    message="rfdetr training queue submission failed",
                    payload={
                        "state": "failed",
                        "error_message": str(exc),
                        "progress": {"stage": "failed"},
                        "result": {
                            "dataset_export_id": dataset_export.dataset_export_id,
                            "dataset_export_manifest_key": dataset_export.manifest_object_key,
                        },
                    },
                )
            )
            raise
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=created_task.task_id,
                event_type="status",
                message="rfdetr training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": self.training_queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return RfdetrTrainingTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=self.training_queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
        )

    def _validate_request(self, request: RfdetrTrainingTaskRequest) -> None:
        """校验 RF-DETR detection 训练请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.output_model_name.strip():
            raise InvalidRequestError("output_model_name 不能为空")
        if not request.recipe_id.strip():
            raise InvalidRequestError("recipe_id 不能为空")
        if request.model_scale not in RFDETR_DETECTION_SCALES:
            raise InvalidRequestError(
                "RF-DETR detection 不支持指定 model_scale",
                details={
                    "model_scale": request.model_scale,
                    "supported_scales": list(RFDETR_DETECTION_SCALES),
                },
            )
        if not request.dataset_export_id and not request.dataset_export_manifest_key:
            raise InvalidRequestError(
                "dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个"
            )

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交训练任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交 RF-DETR 训练任务时缺少 queue backend")
        return self.queue_backend

    def _resolve_dataset_export(self, request: RfdetrTrainingTaskRequest) -> DatasetExport:
        """按 id 或 manifest key 解析训练输入 DatasetExport。"""

        export_by_id = None
        if request.dataset_export_id:
            uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
            try:
                export_by_id = uow.dataset_exports.get_dataset_export(request.dataset_export_id)
            finally:
                uow.close()
        export_by_manifest = None
        if request.dataset_export_manifest_key:
            uow = SqlAlchemyUnitOfWork(self.session_factory.create_session())
            try:
                export_by_manifest = uow.dataset_exports.get_dataset_export_by_manifest_object_key(
                    request.dataset_export_manifest_key
                )
            finally:
                uow.close()
        dataset_export = export_by_id or export_by_manifest
        if dataset_export is None:
            raise ResourceNotFoundError("找不到可用于 RF-DETR 训练的 DatasetExport")
        if (
            export_by_id is not None
            and export_by_manifest is not None
            and export_by_id.dataset_export_id != export_by_manifest.dataset_export_id
        ):
            raise InvalidRequestError(
                "dataset_export_id 与 dataset_export_manifest_key 不属于同一个 DatasetExport",
                details={
                    "dataset_export_id": export_by_id.dataset_export_id,
                    "manifest_object_key": request.dataset_export_manifest_key,
                },
            )
        if dataset_export.project_id != request.project_id:
            raise InvalidRequestError(
                "请求中的 project_id 与 DatasetExport 不一致",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        if dataset_export.status != "completed":
            raise InvalidRequestError(
                "当前 DatasetExport 尚未完成，不能用于训练",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "status": dataset_export.status,
                },
            )
        if dataset_export.format_id != RFDETR_DEFAULT_DATASET_FORMAT:
            raise InvalidRequestError(
                "RF-DETR detection 训练当前只支持 coco-detection-v1",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "format_id": dataset_export.format_id,
                },
            )
        if (
            dataset_export.manifest_object_key is None
            or not dataset_export.manifest_object_key.strip()
        ):
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 manifest_object_key，不能用于训练",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        return dataset_export

    def _build_task_spec(
        self,
        *,
        request: RfdetrTrainingTaskRequest,
        dataset_export: DatasetExport,
    ) -> dict[str, object]:
        """构造持久化到任务记录与队列的训练规格。"""

        task_spec: dict[str, object] = {
            "project_id": request.project_id,
            "recipe_id": request.recipe_id,
            "model_type": self.model_type,
            "task_type": self.task_type,
            "model_scale": request.model_scale,
            "output_model_name": request.output_model_name,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "extra_options": dict(request.extra_options),
        }
        if request.warm_start_model_version_id is not None:
            task_spec["warm_start_model_version_id"] = (
                request.warm_start_model_version_id
            )
        if request.evaluation_interval is not None:
            task_spec["evaluation_interval"] = request.evaluation_interval
        if request.max_epochs is not None:
            task_spec["max_epochs"] = request.max_epochs
        if request.batch_size is not None:
            task_spec["batch_size"] = request.batch_size
        if request.gpu_count is not None:
            task_spec["gpu_count"] = request.gpu_count
        if request.precision is not None:
            task_spec["precision"] = request.precision
        if request.input_size is not None:
            task_spec["input_size"] = list(request.input_size)
        return task_spec
