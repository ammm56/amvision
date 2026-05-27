"""YOLO 主线 detection 训练任务适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.queue import QueueBackend
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.detection_training_rules import (
    DetectionTrainingOutputFiles,
    build_detection_metrics_summary_payload,
    build_detection_runtime_summary_payload,
    build_detection_training_config_payload,
    build_detection_training_model_version_metadata,
    build_detection_training_summary_base,
    build_detection_validation_summary_payload,
)
from backend.service.application.models.yolo_primary_detection_training import (
    YOLO_PRIMARY_BOOTSTRAP_IMPLEMENTATION_MODE,
    YoloPrimaryDetectionTrainingExecutionRequest,
    YoloPrimaryDetectionTrainingExecutionResult,
    YoloPrimaryTrainingBatchProgress,
    YoloPrimaryTrainingEpochProgress,
    run_yolo_primary_detection_training,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLO_PRIMARY_TRAINING_TASK_KIND = "yolo-primary-training"
YOLO_PRIMARY_TRAINING_QUEUE_NAME = "yolo-primary-trainings"


@dataclass(frozen=True)
class YoloPrimaryTrainingTaskRequest:
    """描述一次 YOLO 主线 detection 训练任务创建请求。"""

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
class YoloPrimaryTrainingTaskSubmission:
    """描述一次 YOLO 主线 detection 训练任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str


@dataclass(frozen=True)
class YoloPrimaryTrainingTaskResult:
    """描述一次 YOLO 主线 detection 训练任务处理结果。"""

    task_id: str
    status: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    output_object_prefix: str
    checkpoint_object_key: str
    latest_checkpoint_object_key: str | None = None
    labels_object_key: str | None = None
    metrics_object_key: str | None = None
    validation_metrics_object_key: str | None = None
    summary_object_key: str | None = None
    best_metric_name: str | None = None
    best_metric_value: float | None = None
    summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _ResolvedWarmStartReference:
    """描述一次 warm start 请求解析出的源模型版本信息。"""

    source_model_version_id: str
    source_kind: str
    source_model_name: str
    source_model_scale: str
    checkpoint_storage_uri: str
    checkpoint_path: Path


class SqlAlchemyYoloPrimaryTrainingTaskService:
    """基于现有任务系统的 YOLO 主线 detection 训练任务适配器。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    training_task_kind = YOLO_PRIMARY_TRAINING_TASK_KIND
    training_queue_name = YOLO_PRIMARY_TRAINING_QUEUE_NAME
    model_service_cls: type | None = None
    output_registration_cls: type | None = None
    task_spec_cls: type | None = None
    request_cls = YoloPrimaryTrainingTaskRequest
    task_result_cls = YoloPrimaryTrainingTaskResult
    execution_request_cls = YoloPrimaryDetectionTrainingExecutionRequest
    training_runner = staticmethod(run_yolo_primary_detection_training)
    implementation_mode = YOLO_PRIMARY_BOOTSTRAP_IMPLEMENTATION_MODE
    file_types: Any = None
    default_spec: Any = None

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        spec: object | None = None,
    ) -> None:
        """初始化 YOLO 主线 detection 训练任务适配器。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.spec = spec if spec is not None else self._resolve_default_spec()
        self.task_service = SqlAlchemyTaskService(session_factory)

    def _resolve_default_spec(self) -> object:
        """返回当前模型分类默认使用的模型规格。"""

        return _require_hook_value("default_spec", self.default_spec, model_label=self.model_label)

    def _resolve_training_task_kind(self) -> str:
        """返回当前模型分类训练任务种类。"""

        value = _require_hook_value(
            "training_task_kind",
            self.training_task_kind,
            model_label=self.model_label,
        )
        return str(value)

    def _resolve_training_queue_name(self) -> str:
        """返回当前模型分类训练队列名称。"""

        value = _require_hook_value(
            "training_queue_name",
            self.training_queue_name,
            model_label=self.model_label,
        )
        return str(value)

    def _resolve_model_service_cls(self) -> type:
        """返回当前模型分类绑定的模型服务类型。"""

        return _require_hook_value("model_service_cls", self.model_service_cls, model_label=self.model_label)

    def _resolve_output_registration_cls(self) -> type:
        """返回当前模型分类训练输出登记类型。"""

        return _require_hook_value(
            "output_registration_cls",
            self.output_registration_cls,
            model_label=self.model_label,
        )

    def _resolve_task_spec_cls(self) -> type:
        """返回当前模型分类任务规格类型。"""

        return _require_hook_value("task_spec_cls", self.task_spec_cls, model_label=self.model_label)

    def _resolve_request_cls(self) -> type:
        """返回当前模型分类训练请求类型。"""

        return _require_hook_value("request_cls", self.request_cls, model_label=self.model_label)

    def _resolve_task_result_cls(self) -> type:
        """返回当前模型分类训练结果类型。"""

        return _require_hook_value("task_result_cls", self.task_result_cls, model_label=self.model_label)

    def _resolve_execution_request_cls(self) -> type:
        """返回当前模型分类训练执行请求类型。"""

        return _require_hook_value(
            "execution_request_cls",
            self.execution_request_cls,
            model_label=self.model_label,
        )

    def _resolve_training_runner(self) -> Callable[..., object]:
        """返回当前模型分类训练执行函数。"""

        return _require_hook_value("training_runner", self.training_runner, model_label=self.model_label)

    def _resolve_file_types(self) -> object:
        """返回当前模型分类文件类型集合。"""

        return _require_hook_value("file_types", self.file_types, model_label=self.model_label)

    def submit_training_task(
        self,
        request: YoloPrimaryTrainingTaskRequest,
        *,
        created_by: str | None = None,
        display_name: str = "",
    ) -> YoloPrimaryTrainingTaskSubmission:
        """创建并入队一条 YOLO 主线 detection 训练任务。"""

        self._validate_request(request)
        queue_backend = self._require_queue_backend()
        training_task_kind = self._resolve_training_task_kind()
        training_queue_name = self._resolve_training_queue_name()
        dataset_export = self._resolve_dataset_export(request)
        task_spec = self._build_task_spec(request=request, dataset_export=dataset_export)
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                project_id=request.project_id,
                task_kind=training_task_kind,
                display_name=display_name.strip()
                or f"{self.model_type} training {dataset_export.dataset_export_id}",
                created_by=created_by,
                task_spec=task_spec,
                worker_pool=training_task_kind,
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
                queue_name=training_queue_name,
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
                    message=f"{self.model_type} training queue submission failed",
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
                message=f"{self.model_type} training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": queue_task.queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return YoloPrimaryTrainingTaskSubmission(
            task_id=created_task.task_id,
            status="queued",
            queue_name=queue_task.queue_name,
            queue_task_id=queue_task.task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key or "",
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
        )

    def process_training_task(self, task_id: str) -> YoloPrimaryTrainingTaskResult:
        """执行一条已入队的 YOLOv8 detection 训练任务。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self._require_training_task(task_id)
        existing_result = self._build_existing_result(task_record)
        if task_record.state == "succeeded" and existing_result is not None:
            return existing_result
        if task_record.state == "running":
            raise InvalidRequestError(
                "当前训练任务正在执行，不能重复执行",
                details={"task_id": task_id},
            )
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError(
                "当前训练任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        request = self._build_request_from_task_record(task_record)
        dataset_export = self._resolve_dataset_export(request)
        if dataset_export.manifest_object_key is None:
            raise ServiceConfigurationError(
                "当前训练任务缺少有效的导出 manifest 路径",
                details={"task_id": task_id},
            )
        manifest_payload = dataset_storage.read_json(dataset_export.manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise ServiceConfigurationError(
                "当前训练输入 manifest 内容不合法",
                details={"manifest_object_key": dataset_export.manifest_object_key},
            )

        warm_start_reference = self._resolve_warm_start_reference(request)
        attempt_no = max(1, int(task_record.current_attempt_no) + 1)
        output_object_prefix = self._build_output_object_prefix(task_id)
        output_files = DetectionTrainingOutputFiles(
            output_object_prefix=output_object_prefix,
            checkpoint_object_key=f"{output_object_prefix}/artifacts/checkpoints/best.pt",
            latest_checkpoint_object_key=f"{output_object_prefix}/artifacts/checkpoints/latest.pt",
            labels_object_key=f"{output_object_prefix}/artifacts/labels/labels.txt",
            metrics_object_key=f"{output_object_prefix}/artifacts/reports/training-metrics.json",
            validation_metrics_object_key=(
                f"{output_object_prefix}/artifacts/reports/validation-metrics.json"
            ),
            summary_object_key=f"{output_object_prefix}/artifacts/reports/training-summary.json",
        )
        latest_checkpoint_object_key = output_files.latest_checkpoint_object_key
        labels_object_key = output_files.labels_object_key
        metrics_object_key = output_files.metrics_object_key
        validation_metrics_object_key = output_files.validation_metrics_object_key
        summary_object_key = output_files.summary_object_key
        if (
            latest_checkpoint_object_key is None
            or labels_object_key is None
            or metrics_object_key is None
            or validation_metrics_object_key is None
            or summary_object_key is None
        ):
            raise ServiceConfigurationError("当前 YOLOv8 训练输出文件布局不完整")

        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message=f"{self.model_type} training started",
                payload={
                    "state": "running",
                    "started_at": self._now_iso(),
                    "attempt_no": attempt_no,
                    "progress": {"stage": "training", "percent": 5.0},
                },
            )
        )

        try:
            execution_result = self._resolve_training_runner()(
                self._resolve_execution_request_cls()(
                    dataset_storage=dataset_storage,
                    manifest_payload=manifest_payload,
                    model_scale=request.model_scale,
                    model_type=self.model_type,
                    implementation_mode=self.implementation_mode,
                    evaluation_interval=request.evaluation_interval,
                    max_epochs=request.max_epochs,
                    batch_size=request.batch_size,
                    gpu_count=request.gpu_count,
                    precision=request.precision,
                    warm_start_checkpoint_path=(
                        warm_start_reference.checkpoint_path
                        if warm_start_reference is not None
                        else None
                    ),
                    warm_start_source_summary=(
                        self._build_warm_start_source_summary(warm_start_reference)
                        if warm_start_reference is not None
                        else None
                    ),
                    input_size=request.input_size,
                    extra_options=dict(request.extra_options),
                    batch_callback=lambda progress: self._append_batch_progress(task_id, progress),
                    epoch_callback=lambda progress: self._append_epoch_progress(task_id, progress),
                )
            )
            dataset_storage.write_bytes(
                output_files.checkpoint_object_key,
                execution_result.checkpoint_bytes,
            )
            dataset_storage.write_bytes(
                latest_checkpoint_object_key,
                execution_result.latest_checkpoint_bytes,
            )
            dataset_storage.write_text(
                labels_object_key,
                "".join(f"{label}\n" for label in execution_result.category_names),
            )
            dataset_storage.write_json(metrics_object_key, execution_result.metrics_payload)
            dataset_storage.write_json(
                validation_metrics_object_key,
                execution_result.validation_metrics_payload,
            )

            summary = self._build_training_summary(
                task_id=task_id,
                request=request,
                dataset_export=dataset_export,
                execution_result=execution_result,
                output_files=output_files,
            )
            model_version_id = self._register_training_output_model_version(
                task_record=task_record,
                request=request,
                dataset_export=dataset_export,
                output_files=output_files,
                execution_result=execution_result,
                summary=summary,
            )
            summary["model_version_id"] = model_version_id
            dataset_storage.write_json(summary_object_key, summary)

            task_result = YoloPrimaryTrainingTaskResult(
                task_id=task_id,
                status="succeeded",
                dataset_export_id=dataset_export.dataset_export_id,
                dataset_export_manifest_key=dataset_export.manifest_object_key,
                dataset_version_id=dataset_export.dataset_version_id,
                format_id=dataset_export.format_id,
                output_object_prefix=output_files.output_object_prefix,
                checkpoint_object_key=output_files.checkpoint_object_key,
                latest_checkpoint_object_key=output_files.latest_checkpoint_object_key,
                labels_object_key=output_files.labels_object_key,
                metrics_object_key=output_files.metrics_object_key,
                validation_metrics_object_key=output_files.validation_metrics_object_key,
                summary_object_key=output_files.summary_object_key,
                best_metric_name=execution_result.best_metric_name,
                best_metric_value=execution_result.best_metric_value,
                summary=summary,
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message=f"{self.model_type} training completed",
                    payload={
                        "state": "succeeded",
                        "finished_at": self._now_iso(),
                        "progress": {"stage": "completed", "percent": 100.0},
                        "result": self._serialize_task_result(task_result),
                    },
                )
            )
            return task_result
        except Exception as error:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message=f"{self.model_type} training failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "progress": {"stage": "failed", "percent": 100.0},
                        "error_message": str(error),
                    },
                )
            )
            raise

    def _validate_request(self, request: YoloPrimaryTrainingTaskRequest) -> None:
        """校验训练任务创建请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.recipe_id.strip():
            raise InvalidRequestError("recipe_id 不能为空")
        if not request.model_scale.strip():
            raise InvalidRequestError("model_scale 不能为空")
        if not self.spec.supports_model_scale(request.model_scale):
            raise InvalidRequestError(
                f"当前不支持指定的 {self.model_label} model_scale",
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
            raise InvalidRequestError(f"当前 {self.model_label} detection 训练适配器暂不支持 fp8")
        if request.input_size is not None:
            if len(request.input_size) != 2 or any(not isinstance(item, int) for item in request.input_size):
                raise InvalidRequestError("input_size 必须是包含两个整数的尺寸")
            if any(item < 1 for item in request.input_size):
                raise InvalidRequestError("input_size 必须大于 0")
            if any(item % 32 != 0 for item in request.input_size):
                raise InvalidRequestError(f"{self.model_label} 训练输入尺寸必须是 32 的倍数")
        if not request.dataset_export_id and not request.dataset_export_manifest_key:
            raise InvalidRequestError(
                "dataset_export_id 和 dataset_export_manifest_key 至少需要提供一个"
            )

    def _require_queue_backend(self) -> QueueBackend:
        """返回提交训练任务必需的队列后端。"""

        if self.queue_backend is None:
            raise ServiceConfigurationError("提交训练任务时缺少 queue backend")
        return self.queue_backend

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回执行训练任务必需的数据文件存储服务。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("执行训练任务时缺少 dataset storage")
        return self.dataset_storage

    def _resolve_dataset_export(self, request: YoloPrimaryTrainingTaskRequest) -> DatasetExport:
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
                f"当前 {self.model_label} detection 训练只接受 YOLO detection 导出格式",
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
        request: YoloPrimaryTrainingTaskRequest,
        dataset_export: DatasetExport,
    ) -> dict[str, object]:
        """构建 YOLOv8 detection 训练任务使用的 task_spec。"""

        task_spec = self._resolve_task_spec_cls()(
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
        if task_record.task_kind != self._resolve_training_task_kind():
            raise InvalidRequestError(
                f"当前任务不是 {self.model_label} detection 训练任务",
                details={"task_id": task_id, "task_kind": task_record.task_kind},
            )
        return task_record

    def _build_request_from_task_record(
        self,
        task_record: TaskRecord,
    ) -> YoloPrimaryTrainingTaskRequest:
        """把任务记录中的 task_spec 还原成训练请求对象。"""

        task_spec = dict(task_record.task_spec)
        raw_input_size = task_spec.get("input_size")
        input_size = None
        if isinstance(raw_input_size, list | tuple) and len(raw_input_size) == 2:
            input_size = (int(raw_input_size[0]), int(raw_input_size[1]))
        return self._resolve_request_cls()(
            project_id=str(task_spec.get("project_id") or task_record.project_id),
            dataset_export_id=self._read_optional_str(task_spec.get("dataset_export_id")),
            dataset_export_manifest_key=self._read_optional_str(
                task_spec.get("dataset_export_manifest_key")
            ),
            recipe_id=str(task_spec.get("recipe_id") or ""),
            model_scale=str(task_spec.get("model_scale") or ""),
            output_model_name=str(task_spec.get("output_model_name") or ""),
            warm_start_model_version_id=self._read_optional_str(
                task_spec.get("warm_start_model_version_id")
            ),
            evaluation_interval=self._read_optional_int(task_spec.get("evaluation_interval")),
            max_epochs=self._read_optional_int(task_spec.get("max_epochs")),
            batch_size=self._read_optional_int(task_spec.get("batch_size")),
            gpu_count=self._read_optional_int(task_spec.get("gpu_count")),
            precision=self._read_optional_str(task_spec.get("precision")),
            input_size=input_size,
            extra_options=(
                dict(task_spec.get("extra_options"))
                if isinstance(task_spec.get("extra_options"), dict)
                else {}
            ),
        )

    def _append_batch_progress(
        self,
        task_id: str,
        progress: YoloPrimaryTrainingBatchProgress,
    ) -> None:
        """回写单个 batch 的进度事件。"""

        percent = 5.0 + ((progress.global_iteration / max(progress.total_iterations, 1)) * 75.0)
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="progress",
                message=f"{self.model_type} training batch progressed",
                payload={
                    "progress": {
                        "stage": "training",
                        "granularity": "batch",
                        "epoch": progress.epoch,
                        "max_epochs": progress.max_epochs,
                        "iteration": progress.iteration,
                        "max_iterations": progress.max_iterations,
                        "global_iteration": progress.global_iteration,
                        "total_iterations": progress.total_iterations,
                        "input_size": list(progress.input_size),
                        "learning_rate": progress.learning_rate,
                        "train_metrics": dict(progress.train_metrics),
                        "percent": round(percent, 3),
                    }
                },
            )
        )

    def _append_epoch_progress(
        self,
        task_id: str,
        progress: YoloPrimaryTrainingEpochProgress,
    ) -> None:
        """回写单轮训练结束后的进度事件。"""

        percent = 80.0 + ((progress.epoch / max(progress.max_epochs, 1)) * 15.0)
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="progress",
                message=f"{self.model_type} training epoch progressed",
                payload={
                    "progress": {
                        "stage": "training",
                        "granularity": "epoch",
                        "epoch": progress.epoch,
                        "max_epochs": progress.max_epochs,
                        "evaluation_interval": progress.evaluation_interval,
                        "validation_ran": progress.validation_ran,
                        "evaluated_epochs": list(progress.evaluated_epochs),
                        "train_metrics": dict(progress.train_metrics),
                        "validation_metrics": dict(progress.validation_metrics),
                        "current_metric_name": progress.current_metric_name,
                        "current_metric_value": progress.current_metric_value,
                        "best_metric_name": progress.best_metric_name,
                        "best_metric_value": progress.best_metric_value,
                        "percent": round(percent, 3),
                    }
                },
            )
        )

    def _build_output_object_prefix(self, task_id: str) -> str:
        """构建训练任务输出目录前缀。"""

        return f"task-runs/training/{task_id}"

    def _build_training_summary(
        self,
        *,
        task_id: str,
        request: YoloPrimaryTrainingTaskRequest,
        dataset_export: DatasetExport,
        execution_result: YoloPrimaryDetectionTrainingExecutionResult,
        output_files: DetectionTrainingOutputFiles,
    ) -> dict[str, object]:
        """构建训练完成后保存到 summary 文件的内容。"""

        training_config = build_detection_training_config_payload(
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
            extra_options=request.extra_options,
        )
        validation_summary = build_detection_validation_summary_payload(
            enabled=execution_result.validation_split_name is not None,
            split_name=execution_result.validation_split_name,
            sample_count=execution_result.validation_sample_count,
            evaluation_interval=execution_result.evaluation_interval,
            final_metrics=(
                dict(execution_result.validation_metrics_payload.get("final_metrics", {}))
                if isinstance(execution_result.validation_metrics_payload, dict)
                else {}
            ),
        )
        summary = build_detection_training_summary_base(
            task_id=task_id,
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_export_manifest_key=dataset_export.manifest_object_key,
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            recipe_id=request.recipe_id,
            model_scale=request.model_scale,
            output_model_name=request.output_model_name,
            implementation_mode=execution_result.implementation_mode,
            sample_count=execution_result.sample_count,
            train_sample_count=execution_result.train_sample_count,
            split_names=execution_result.split_names,
            category_names=execution_result.category_names,
            input_size=execution_result.input_size,
            batch_size=execution_result.batch_size,
            max_epochs=execution_result.max_epochs,
            device=execution_result.device,
            gpu_count=execution_result.gpu_count,
            device_ids=execution_result.device_ids,
            distributed_mode=execution_result.distributed_mode,
            requested_gpu_count=request.gpu_count,
            precision=execution_result.precision,
            requested_precision=request.precision or execution_result.precision,
            evaluation_interval=execution_result.evaluation_interval,
            parameter_count=execution_result.parameter_count,
            best_metric_name=execution_result.best_metric_name,
            best_metric_value=execution_result.best_metric_value,
            output_files=output_files,
            training_config=training_config,
            validation_summary=validation_summary,
            warm_start_summary=dict(execution_result.warm_start_summary),
        )
        summary["metrics_payload"] = execution_result.metrics_payload
        summary["validation_metrics_payload"] = execution_result.validation_metrics_payload
        return summary

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        request: YoloPrimaryTrainingTaskRequest,
        dataset_export: DatasetExport,
        output_files: DetectionTrainingOutputFiles,
        execution_result: YoloPrimaryDetectionTrainingExecutionResult,
        summary: dict[str, object],
    ) -> str:
        """把训练输出登记为 ModelVersion。"""

        model_service = self._resolve_model_service_cls()(session_factory=self.session_factory)
        runtime_summary = build_detection_runtime_summary_payload(
            device=execution_result.device,
            gpu_count=execution_result.gpu_count,
            device_ids=execution_result.device_ids,
            precision=execution_result.precision,
            distributed_mode=execution_result.distributed_mode,
        )
        metrics_summary = build_detection_metrics_summary_payload(
            best_metric_name=execution_result.best_metric_name,
            best_metric_value=execution_result.best_metric_value,
        )
        return model_service.register_training_output(
            self._resolve_output_registration_cls()(
                project_id=request.project_id,
                training_task_id=task_record.task_id,
                model_name=request.output_model_name,
                model_scale=request.model_scale,
                dataset_version_id=dataset_export.dataset_version_id,
                parent_version_id=request.warm_start_model_version_id,
                checkpoint_file_id=self._build_training_output_file_id(task_record.task_id, "checkpoint"),
                checkpoint_file_uri=output_files.checkpoint_object_key,
                labels_file_id=self._build_training_output_file_id(task_record.task_id, "labels"),
                labels_file_uri=output_files.labels_object_key,
                metrics_file_id=self._build_training_output_file_id(task_record.task_id, "metrics"),
                metrics_file_uri=output_files.metrics_object_key,
                metadata=build_detection_training_model_version_metadata(
                    dataset_export_id=dataset_export.dataset_export_id,
                    manifest_object_key=dataset_export.manifest_object_key,
                    category_names=execution_result.category_names,
                    input_size=execution_result.input_size,
                    training_config=dict(summary["training_config"]),
                    runtime_summary=runtime_summary,
                    warm_start_summary=dict(execution_result.warm_start_summary),
                    registration_kind="best-checkpoint",
                    output_files=output_files,
                    metrics_summary=metrics_summary,
                ),
            )
        )

    def _build_training_output_file_id(self, task_id: str, output_name: str) -> str:
        """基于训练任务 id 生成输出文件记录 id。"""

        return f"{task_id}-{output_name}"

    def _resolve_warm_start_reference(
        self,
        request: YoloPrimaryTrainingTaskRequest,
    ) -> _ResolvedWarmStartReference | None:
        """按 warm_start_model_version_id 解析可加载的 checkpoint。"""

        if request.warm_start_model_version_id is None:
            return None
        model_service = self._resolve_model_service_cls()(session_factory=self.session_factory)
        model_version = model_service.get_model_version(request.warm_start_model_version_id)
        if model_version is None:
            raise ResourceNotFoundError(
                "找不到指定的 warm start ModelVersion",
                details={"model_version_id": request.warm_start_model_version_id},
            )
        model = model_service.get_model(model_version.model_id)
        if model is None:
            raise ResourceNotFoundError(
                "指定的 warm start ModelVersion 缺少 Model 主记录",
                details={"model_version_id": request.warm_start_model_version_id},
            )
        checkpoint_file = next(
            (
                model_file
                for model_file in model_service.list_model_files(
                    model_version_id=request.warm_start_model_version_id
                )
                if model_file.file_type == self._resolve_file_types().checkpoint_file_type
            ),
            None,
        )
        if checkpoint_file is None:
            raise ServiceConfigurationError(
                "指定的 warm start ModelVersion 缺少 checkpoint 文件",
                details={"model_version_id": request.warm_start_model_version_id},
            )
        checkpoint_storage_uri = checkpoint_file.storage_uri
        if "://" in checkpoint_storage_uri:
            raise ServiceConfigurationError(
                "当前 warm start 仅支持本地对象路径 checkpoint",
                details={
                    "model_version_id": request.warm_start_model_version_id,
                    "storage_uri": checkpoint_storage_uri,
                },
            )
        checkpoint_path = self._require_dataset_storage().resolve(checkpoint_storage_uri)
        if not checkpoint_path.is_file():
            raise ServiceConfigurationError(
                "指定的 warm start checkpoint 文件不存在",
                details={"checkpoint_storage_uri": checkpoint_storage_uri},
            )
        return _ResolvedWarmStartReference(
            source_model_version_id=model_version.model_version_id,
            source_kind=model_version.source_kind,
            source_model_name=model.model_name,
            source_model_scale=model.model_scale,
            checkpoint_storage_uri=checkpoint_storage_uri,
            checkpoint_path=checkpoint_path,
        )

    def _build_warm_start_source_summary(
        self,
        warm_start_reference: _ResolvedWarmStartReference,
    ) -> dict[str, object]:
        """把 warm start 来源记录成训练执行可消费的摘要。"""

        return {
            "source_model_version_id": warm_start_reference.source_model_version_id,
            "source_kind": warm_start_reference.source_kind,
            "source_model_name": warm_start_reference.source_model_name,
            "source_model_scale": warm_start_reference.source_model_scale,
        }

    def _build_existing_result(
        self,
        task_record: TaskRecord,
    ) -> YoloPrimaryTrainingTaskResult | None:
        """尝试从已保存的任务结果中重建训练结果对象。"""

        result = dict(task_record.result)
        required_fields = (
            "dataset_export_id",
            "dataset_export_manifest_key",
            "dataset_version_id",
            "format_id",
            "output_object_prefix",
            "checkpoint_object_key",
        )
        if not all(isinstance(result.get(field_name), str) for field_name in required_fields):
            return None
        return self._resolve_task_result_cls()(
            task_id=task_record.task_id,
            status=str(result.get("status") or task_record.state),
            dataset_export_id=str(result["dataset_export_id"]),
            dataset_export_manifest_key=str(result["dataset_export_manifest_key"]),
            dataset_version_id=str(result["dataset_version_id"]),
            format_id=str(result["format_id"]),
            output_object_prefix=str(result["output_object_prefix"]),
            checkpoint_object_key=str(result["checkpoint_object_key"]),
            latest_checkpoint_object_key=self._read_optional_str(result.get("latest_checkpoint_object_key")),
            labels_object_key=self._read_optional_str(result.get("labels_object_key")),
            metrics_object_key=self._read_optional_str(result.get("metrics_object_key")),
            validation_metrics_object_key=self._read_optional_str(
                result.get("validation_metrics_object_key")
            ),
            summary_object_key=self._read_optional_str(result.get("summary_object_key")),
            best_metric_name=self._read_optional_str(result.get("best_metric_name")),
            best_metric_value=self._read_optional_float(result.get("best_metric_value")),
            summary=dict(result.get("summary") or {}),
        )

    def _serialize_task_result(
        self,
        task_result: YoloPrimaryTrainingTaskResult,
    ) -> dict[str, object]:
        """把训练结果对象转成可保存到任务结果里的字典。"""

        return {
            "status": task_result.status,
            "dataset_export_id": task_result.dataset_export_id,
            "dataset_export_manifest_key": task_result.dataset_export_manifest_key,
            "dataset_version_id": task_result.dataset_version_id,
            "format_id": task_result.format_id,
            "output_object_prefix": task_result.output_object_prefix,
            "checkpoint_object_key": task_result.checkpoint_object_key,
            "latest_checkpoint_object_key": task_result.latest_checkpoint_object_key,
            "labels_object_key": task_result.labels_object_key,
            "metrics_object_key": task_result.metrics_object_key,
            "validation_metrics_object_key": task_result.validation_metrics_object_key,
            "summary_object_key": task_result.summary_object_key,
            "best_metric_name": task_result.best_metric_name,
            "best_metric_value": task_result.best_metric_value,
            "summary": dict(task_result.summary),
            "model_version_id": self._read_optional_str(task_result.summary.get("model_version_id")),
        }

    def _read_optional_str(self, value: object) -> str | None:
        """读取可选字符串字段。"""

        if isinstance(value, str) and value.strip():
            return value
        return None

    def _read_optional_int(self, value: object) -> int | None:
        """读取可选整数字段。"""

        if isinstance(value, int):
            return value
        return None

    def _read_optional_float(self, value: object) -> float | None:
        """读取可选浮点数字段。"""

        if isinstance(value, int | float):
            return float(value)
        return None

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()


def _require_hook_value(hook_name: str, value: object, *, model_label: str) -> Any:
    """返回共享训练层要求子类提供的 hook 值。"""

    if value is None:
        raise ServiceConfigurationError(
            f"当前 {model_label} 训练适配器缺少 {hook_name} 配置",
            details={"hook_name": hook_name, "model_label": model_label},
        )
    return value
