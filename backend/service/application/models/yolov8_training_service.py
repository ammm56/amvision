"""YOLOv8 detection 训练任务适配器。"""

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
from backend.service.domain.models.yolov8_model_spec import (
    DEFAULT_YOLOV8_MODEL_SPEC,
    YoloV8ModelSpec,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.domain.tasks.yolov8_task_specs import YoloV8TrainingTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLOV8_TRAINING_TASK_KIND = "yolov8-training"
YOLOV8_TRAINING_QUEUE_NAME = "yolov8-trainings"


@dataclass(frozen=True)
class YoloV8TrainingTaskRequest:
    """描述一次 YOLOv8 detection 训练任务创建请求。"""

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
class YoloV8TrainingTaskSubmission:
    """描述一次 YOLOv8 detection 训练任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str


class SqlAlchemyYoloV8TrainingTaskService:
    """基于现有任务系统的 YOLOv8 detection 训练任务适配器。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        spec: YoloV8ModelSpec = DEFAULT_YOLOV8_MODEL_SPEC,
    ) -> None:
        """初始化 YOLOv8 detection 训练任务适配器。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.spec = spec
        self.task_service = SqlAlchemyTaskService(session_factory)

    def submit_training_task(
        self,
        request: YoloV8TrainingTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloV8TrainingTaskSubmission:
        """创建并入队一条 YOLOv8 detection 训练任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        dataset_export = self._resolve_dataset_export(request)
        task_spec = self._build_task_spec(request=request, dataset_export=dataset_export)
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=YOLOV8_TRAINING_TASK_KIND,
                display_name=display_name.strip()
                or f"yolov8 training {dataset_export.dataset_export_id}",
                created_by=created_by,
                task_spec=task_spec,
                worker_pool=YOLOV8_TRAINING_TASK_KIND,
                metadata={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_id": dataset_export.dataset_id,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                    "model_type": self.spec.model_name,
                    "task_type": DETECTION_TASK_TYPE,
                },
            )
        )
        try:
            queue_task = queue_backend.enqueue(
                queue_name=YOLOV8_TRAINING_QUEUE_NAME,
                payload={"task_id": created_task.task_id},
                metadata={
                    "project_id": request.project_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "dataset_version_id": dataset_export.dataset_version_id,
                    "format_id": dataset_export.format_id,
                    "model_type": self.spec.model_name,
                },
            )
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="result",
                    message="yolov8 training queue submission failed",
                    payload={
                        "state": "failed",
                        "error_message": str(error),
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
                message="yolov8 training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloV8TrainingTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
        )

    def process_training_task(self, task_id: str) -> None:
        """执行一条已入队的 YOLOv8 detection 训练任务。

        当前适配器只接通任务边界与持久化合同，底层训练执行尚未接入。
        """

        task_record = self._require_training_task(task_id)
        if task_record.state in {"failed", "cancelled", "succeeded"}:
            raise InvalidRequestError(
                "当前训练任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="yolov8 detection training backend not implemented yet",
                payload={
                    "state": "failed",
                    "progress": {"stage": "failed", "percent": 100.0},
                    "error_message": "当前 YOLOv8 detection 训练执行后端尚未接通",
                },
            )
        )
        raise ServiceConfigurationError(
            "当前 YOLOv8 detection 训练执行后端尚未接通",
            details={"task_id": task_id, "model_type": self.spec.model_name},
        )

    def _validate_request(self, request: YoloV8TrainingTaskRequest) -> None:
        """校验训练任务创建请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.recipe_id.strip():
            raise InvalidRequestError("recipe_id 不能为空")
        if not request.model_scale.strip():
            raise InvalidRequestError("model_scale 不能为空")
        if not self.spec.supports_model_scale(request.model_scale):
            raise InvalidRequestError(
                "当前不支持指定的 YOLOv8 model_scale",
                details={"model_scale": request.model_scale},
            )
        if not request.output_model_name.strip():
            raise InvalidRequestError("output_model_name 不能为空")
        if request.max_epochs is not None and request.max_epochs < 1:
            raise InvalidRequestError("max_epochs 必须大于 0")
        if request.evaluation_interval is not None and request.evaluation_interval < 1:
            raise InvalidRequestError("evaluation_interval 必须大于 0")
        if request.batch_size is not None and request.batch_size < 1:
            raise InvalidRequestError("batch_size 必须大于 0")
        if request.gpu_count is not None and request.gpu_count < 1:
            raise InvalidRequestError("gpu_count 必须大于 0")
        if request.precision is not None and request.precision not in {"fp8", "fp16", "fp32"}:
            raise InvalidRequestError("precision 必须是 fp8、fp16 或 fp32")
        if request.precision == "fp8":
            raise InvalidRequestError("当前 YOLOv8 detection 训练适配器暂不支持 fp8")
        if request.input_size is not None:
            if len(request.input_size) != 2 or any(not isinstance(item, int) for item in request.input_size):
                raise InvalidRequestError("input_size 必须是包含两个整数的尺寸")
            if any(item < 1 for item in request.input_size):
                raise InvalidRequestError("input_size 必须大于 0")
            if any(item % 32 != 0 for item in request.input_size):
                raise InvalidRequestError("YOLOv8 训练输入尺寸必须是 32 的倍数")
        if not request.dataset_export_id and not request.dataset_export_manifest_key:
            raise InvalidRequestError(
                "dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个"
            )

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交训练任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交训练任务时缺少 queue backend")
        return self.queue_backend

    def _resolve_dataset_export(self, request: YoloV8TrainingTaskRequest) -> DatasetExport:
        """根据请求解析训练输入使用的 DatasetExport。"""

        export_by_id = None
        if request.dataset_export_id is not None:
            export_by_id = self._get_dataset_export(request.dataset_export_id)

        export_by_manifest = None
        if request.dataset_export_manifest_key is not None:
            export_by_manifest = self._get_dataset_export_by_manifest(
                request.dataset_export_manifest_key
            )

        dataset_export = export_by_id or export_by_manifest
        if dataset_export is None:
            raise ResourceNotFoundError("找不到可用于训练的 DatasetExport")
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
        expected_format = self.spec.resolve_default_dataset_format(DETECTION_TASK_TYPE)
        if expected_format is not None and dataset_export.format_id != expected_format:
            raise InvalidRequestError(
                "当前 YOLOv8 detection 训练只接受 YOLO detection 导出格式",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "format_id": dataset_export.format_id,
                    "expected_format_id": expected_format,
                },
            )
        if dataset_export.manifest_object_key is None or not dataset_export.manifest_object_key.strip():
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 manifest_object_key，不能用于训练",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        return dataset_export

    def _get_dataset_export(self, dataset_export_id: str) -> DatasetExport:
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

    def _get_dataset_export_by_manifest(self, manifest_object_key: str) -> DatasetExport:
        """按 manifest object key 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export_by_manifest_object_key(
                manifest_object_key
            )
        finally:
            unit_of_work.close()
        if dataset_export is None:
            raise ResourceNotFoundError(
                "找不到指定 manifest_object_key 对应的 DatasetExport",
                details={"manifest_object_key": manifest_object_key},
            )
        return dataset_export

    def _build_task_spec(
        self,
        *,
        request: YoloV8TrainingTaskRequest,
        dataset_export: DatasetExport,
    ) -> dict[str, object]:
        """构建 YOLOv8 detection 训练任务使用的 task_spec。"""

        task_spec = YoloV8TrainingTaskSpec(
            project_id=request.project_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            manifest_object_key=dataset_export.manifest_object_key or "",
            recipe_id=request.recipe_id,
            model_scale=request.model_scale,
            output_model_name=request.output_model_name,
            warm_start_model_version_id=request.warm_start_model_version_id,
            evaluation_interval=request.evaluation_interval,
            max_epochs=request.max_epochs,
            batch_size=request.batch_size,
            gpu_count=request.gpu_count,
            precision=request.precision,
            input_size=request.input_size,
            extra_options=dict(request.extra_options),
        )
        return {
            "project_id": task_spec.project_id,
            "dataset_export_id": task_spec.dataset_export_id,
            "dataset_export_manifest_key": task_spec.dataset_export_manifest_key,
            "manifest_object_key": task_spec.manifest_object_key,
            "recipe_id": task_spec.recipe_id,
            "model_scale": task_spec.model_scale,
            "output_model_name": task_spec.output_model_name,
            "warm_start_model_version_id": task_spec.warm_start_model_version_id,
            "evaluation_interval": task_spec.evaluation_interval,
            "max_epochs": task_spec.max_epochs,
            "batch_size": task_spec.batch_size,
            "gpu_count": task_spec.gpu_count,
            "precision": task_spec.precision,
            "input_size": list(task_spec.input_size) if task_spec.input_size is not None else None,
            "extra_options": dict(task_spec.extra_options),
            "model_type": self.spec.model_name,
            "task_type": DETECTION_TASK_TYPE,
        }

    def _require_training_task(self, task_id: str) -> TaskRecord:
        """读取并校验训练任务主记录。"""

        task_record = self.task_service.get_task(task_id).task
        if task_record.task_kind != YOLOV8_TRAINING_TASK_KIND:
            raise InvalidRequestError(
                "当前任务不是 YOLOv8 detection 训练任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )
        return task_record
