"""RF-DETR detection 训练任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.queue import QueueBackend
from backend.service.application.backends import TrainingBackendRunResult
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.catalog.rfdetr import (
    RfdetrTrainingOutputRegistration,
    SqlAlchemyRfdetrModelService,
)
from backend.service.application.models.training.detection_training_rules import (
    DetectionTrainingOutputFiles,
    build_detection_training_model_version_metadata,
)
from backend.service.application.models.training.rfdetr_detection import (
    RFDETR_IMPL_MODE,
    RfdetrTrainingExecutionRequest,
    RfdetrTrainingExecutionResult,
    run_rfdetr_training,
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
from backend.service.domain.tasks.task_records import TaskRecord
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

        self.session_factory = session_factory
        self.queue_backend = queue_backend
        self.dataset_storage = dataset_storage
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

    def process_training_task(self, task_id: str) -> TrainingBackendRunResult:
        """执行已入队的 RF-DETR detection 训练任务。"""

        dataset_storage = self._require_dataset_storage()
        task_record = self.task_service.get_task(task_id).task
        if task_record.state == "succeeded":
            existing_result = self._build_existing_run_result(task_record)
            if existing_result is not None:
                return existing_result
        if task_record.state == "running":
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务正在执行，不能重复执行",
                details={"task_id": task_id},
            )
        if task_record.state in {"failed", "cancelled"}:
            raise InvalidRequestError(
                "当前 RF-DETR 训练任务已经结束，不能重复执行",
                details={"task_id": task_id, "state": task_record.state},
            )

        payload = self._read_task_payload(task_record)
        dataset_export = self._resolve_dataset_export_from_payload(
            project_id=task_record.project_id,
            payload=payload,
        )
        manifest_object_key = dataset_export.manifest_object_key
        if manifest_object_key is None or not manifest_object_key.strip():
            raise InvalidRequestError(
                "RF-DETR detection 训练任务缺少 manifest_object_key",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        manifest_payload = dataset_storage.read_json(manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise InvalidRequestError("RF-DETR detection 训练 manifest 无效")

        output_prefix = f"task-runs/{task_id}"
        output_files = DetectionTrainingOutputFiles(
            output_object_prefix=output_prefix,
            checkpoint_object_key=f"{output_prefix}/output-files/best-checkpoint.pt",
            latest_checkpoint_object_key=(
                f"{output_prefix}/output-files/latest-checkpoint.pt"
            ),
            labels_object_key=f"{output_prefix}/output-files/labels.txt",
            metrics_object_key=f"{output_prefix}/output-files/train-metrics.json",
            validation_metrics_object_key=(
                f"{output_prefix}/output-files/validation-metrics.json"
            ),
            summary_object_key=f"{output_prefix}/output-files/training-summary.json",
        )
        started_at = self._now_iso()
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="rfdetr training started",
                payload={
                    "state": "running",
                    "started_at": started_at,
                    "progress": {"stage": "running", "percent": 0},
                },
            )
        )

        try:
            execution_result = run_rfdetr_training(
                RfdetrTrainingExecutionRequest(
                    dataset_storage=dataset_storage,
                    manifest_payload=manifest_payload,
                    model_scale=str(payload.get("model_scale") or "nano"),
                    batch_size=int(payload.get("batch_size") or 2),
                    max_epochs=int(payload.get("max_epochs") or 1),
                    input_size=self._read_input_size(payload.get("input_size")),
                    precision=str(payload.get("precision") or "fp32"),
                    extra_options=dict(payload.get("extra_options") or {}),
                )
            )
        except Exception as exc:
            failed_result = {
                "status": "failed",
                "task_id": task_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "format_id": dataset_export.format_id,
                "output_object_prefix": output_prefix,
                "model_type": self.model_type,
                "task_type": self.task_type,
            }
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_id,
                    event_type="result",
                    message="rfdetr training failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "error_message": str(exc),
                        "result": failed_result,
                        "progress": {"stage": "failed", "percent": 100},
                    },
                )
            )
            raise

        dataset_storage.write_bytes(
            output_files.checkpoint_object_key,
            execution_result.latest_checkpoint_bytes,
        )
        if output_files.latest_checkpoint_object_key is not None:
            dataset_storage.write_bytes(
                output_files.latest_checkpoint_object_key,
                execution_result.latest_checkpoint_bytes,
            )
        if output_files.metrics_object_key is not None:
            dataset_storage.write_json(
                output_files.metrics_object_key,
                execution_result.metrics_payload,
            )
        if output_files.validation_metrics_object_key is not None:
            dataset_storage.write_json(
                output_files.validation_metrics_object_key,
                execution_result.validation_metrics_payload,
            )
        if output_files.labels_object_key is not None:
            self._write_labels_text(
                labels_object_key=output_files.labels_object_key,
                labels=execution_result.labels,
            )

        summary = self._build_training_summary(
            task_record=task_record,
            payload=payload,
            dataset_export=dataset_export,
            execution_result=execution_result,
            output_files=output_files,
        )
        model_version_id = self._register_training_output_model_version(
            task_record=task_record,
            payload=payload,
            dataset_export=dataset_export,
            execution_result=execution_result,
            output_files=output_files,
            summary=summary,
        )
        summary["model_version_id"] = model_version_id
        if output_files.summary_object_key is not None:
            dataset_storage.write_json(output_files.summary_object_key, summary)

        task_result = {
            "status": "succeeded",
            "task_id": task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "output_prefix": output_prefix,
            "output_object_prefix": output_prefix,
            "checkpoint_object_key": output_files.checkpoint_object_key,
            "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
            "labels_object_key": output_files.labels_object_key,
            "metrics_object_key": output_files.metrics_object_key,
            "validation_metrics_object_key": output_files.validation_metrics_object_key,
            "summary_object_key": output_files.summary_object_key,
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "labels": list(execution_result.labels),
            "model_version_id": model_version_id,
            "summary": summary,
        }
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="rfdetr training succeeded",
                payload={
                    "state": "succeeded",
                    "finished_at": self._now_iso(),
                    "result": task_result,
                    "progress": {"stage": "succeeded", "percent": 100},
                },
            )
        )
        return self._build_run_result_from_payload(
            task_id=task_id,
            result=task_result,
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

    def _require_dataset_storage(self):
        """返回执行 RF-DETR detection 训练必需的数据集存储。"""

        if self.dataset_storage is None:
            raise ServiceConfigurationError("执行 RF-DETR 训练任务时缺少 dataset storage")
        return self.dataset_storage

    def _read_task_payload(self, task_record: TaskRecord) -> dict[str, object]:
        """从任务记录中读取 RF-DETR detection 训练参数。"""

        metadata_payload = task_record.metadata.get("queue_payload")
        payload: dict[str, object] = {}
        if isinstance(metadata_payload, dict):
            payload.update(metadata_payload)
        payload.update(task_record.task_spec)
        return payload

    def _resolve_dataset_export_from_payload(
        self,
        *,
        project_id: str,
        payload: dict[str, object],
    ) -> DatasetExport:
        """按任务 payload 解析 RF-DETR detection 训练输入 DatasetExport。"""

        dataset_export_id = self._read_optional_str(payload.get("dataset_export_id"))
        manifest_key = self._read_optional_str(payload.get("dataset_export_manifest_key"))
        return self._resolve_dataset_export(
            RfdetrTrainingTaskRequest(
                project_id=project_id,
                recipe_id=str(payload.get("recipe_id") or "default"),
                model_scale=str(payload.get("model_scale") or "nano"),
                output_model_name=str(payload.get("output_model_name") or "rfdetr"),
                dataset_export_id=dataset_export_id,
                dataset_export_manifest_key=manifest_key,
            )
        )

    def _build_training_summary(
        self,
        *,
        task_record: TaskRecord,
        payload: dict[str, object],
        dataset_export: DatasetExport,
        execution_result: RfdetrTrainingExecutionResult,
        output_files: DetectionTrainingOutputFiles,
    ) -> dict[str, object]:
        """构建 RF-DETR detection 训练摘要。"""

        training_config = {
            "recipe_id": str(payload.get("recipe_id") or "default"),
            "model_scale": str(payload.get("model_scale") or "nano"),
            "output_model_name": str(payload.get("output_model_name") or "rfdetr"),
            "batch_size": int(payload.get("batch_size") or 2),
            "max_epochs": int(payload.get("max_epochs") or 1),
            "precision": str(payload.get("precision") or "fp32"),
            "input_size": list(execution_result.aligned_input_size),
            "extra_options": dict(payload.get("extra_options") or {}),
        }
        metrics_summary = {
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
        }
        return {
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "manifest_object_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "model_type": self.model_type,
            "task_type": self.task_type,
            "implementation_mode": RFDETR_IMPL_MODE,
            "category_names": list(execution_result.labels),
            "input_size": list(execution_result.aligned_input_size),
            "training_config": training_config,
            "metrics_summary": metrics_summary,
            "validation": dict(execution_result.validation_metrics_payload),
            "output_files": {
                "output_object_prefix": output_files.output_object_prefix,
                "checkpoint_object_key": output_files.checkpoint_object_key,
                "latest_checkpoint_object_key": output_files.latest_checkpoint_object_key,
                "labels_object_key": output_files.labels_object_key,
                "metrics_object_key": output_files.metrics_object_key,
                "validation_metrics_object_key": output_files.validation_metrics_object_key,
                "summary_object_key": output_files.summary_object_key,
            },
        }

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        payload: dict[str, object],
        dataset_export: DatasetExport,
        execution_result: RfdetrTrainingExecutionResult,
        output_files: DetectionTrainingOutputFiles,
        summary: dict[str, object],
    ) -> str:
        """把 RF-DETR detection 训练输出登记为 ModelVersion。"""

        model_service = SqlAlchemyRfdetrModelService(
            session_factory=self.session_factory
        )
        model_version_metadata = build_detection_training_model_version_metadata(
            dataset_export_id=dataset_export.dataset_export_id,
            manifest_object_key=dataset_export.manifest_object_key,
            category_names=execution_result.labels,
            input_size=execution_result.aligned_input_size,
            training_config=dict(summary["training_config"]),
            runtime_summary={
                "device": "cpu",
                "gpu_count": int(payload.get("gpu_count") or 0),
                "device_ids": [],
                "precision": str(payload.get("precision") or "fp32"),
                "distributed_mode": False,
            },
            warm_start_summary={},
            registration_kind="best-checkpoint",
            output_files=output_files,
            metrics_summary=dict(summary["metrics_summary"]),
        )
        model_version_metadata["implementation_mode"] = RFDETR_IMPL_MODE
        return model_service.register_training_output(
            RfdetrTrainingOutputRegistration(
                project_id=task_record.project_id,
                training_task_id=task_record.task_id,
                model_name=str(payload.get("output_model_name") or "rfdetr"),
                model_scale=str(payload.get("model_scale") or "nano"),
                dataset_version_id=dataset_export.dataset_version_id,
                parent_version_id=self._read_optional_str(
                    payload.get("warm_start_model_version_id")
                ),
                checkpoint_file_id=f"{task_record.task_id}-checkpoint",
                checkpoint_file_uri=output_files.checkpoint_object_key,
                task_type=self.task_type,
                labels_file_id=f"{task_record.task_id}-labels",
                labels_file_uri=output_files.labels_object_key,
                metrics_file_id=f"{task_record.task_id}-metrics",
                metrics_file_uri=output_files.metrics_object_key,
                metadata=model_version_metadata,
            )
        )

    def _write_labels_text(self, *, labels_object_key: str, labels: tuple[str, ...]) -> None:
        """写出 RF-DETR detection 标签文本文件。"""

        content = "\n".join(labels)
        if content:
            content = f"{content}\n"
        self._require_dataset_storage().write_text(labels_object_key, content)

    def _build_existing_run_result(
        self,
        task_record: TaskRecord,
    ) -> TrainingBackendRunResult | None:
        """从已完成任务结果重建 TrainingBackendRunResult。"""

        if not task_record.result:
            return None
        return self._build_run_result_from_payload(
            task_id=task_record.task_id,
            result=dict(task_record.result),
        )

    def _build_run_result_from_payload(
        self,
        *,
        task_id: str,
        result: dict[str, object],
    ) -> TrainingBackendRunResult:
        """把任务 result 转成 TrainingBackendRunResult。"""

        return TrainingBackendRunResult(
            training_task_id=task_id,
            status=str(result.get("status") or "succeeded"),
            dataset_export_id=str(result.get("dataset_export_id") or ""),
            dataset_export_manifest_key=str(
                result.get("dataset_export_manifest_key") or ""
            ),
            dataset_version_id=str(result.get("dataset_version_id") or ""),
            format_id=str(result.get("format_id") or RFDETR_DEFAULT_DATASET_FORMAT),
            output_object_prefix=str(
                result.get("output_object_prefix")
                or result.get("output_prefix")
                or f"task-runs/{task_id}"
            ),
            checkpoint_object_key=str(result.get("checkpoint_object_key") or ""),
            latest_checkpoint_object_key=self._read_optional_str(
                result.get("latest_checkpoint_object_key")
            ),
            labels_object_key=self._read_optional_str(result.get("labels_object_key")),
            metrics_object_key=self._read_optional_str(result.get("metrics_object_key")),
            validation_metrics_object_key=self._read_optional_str(
                result.get("validation_metrics_object_key")
            ),
            summary_object_key=self._read_optional_str(result.get("summary_object_key")),
            best_metric_name=self._read_optional_str(result.get("best_metric_name")),
            best_metric_value=self._read_optional_float(
                result.get("best_metric_value")
            ),
            summary=dict(result.get("summary") or {}),
        )

    def _read_input_size(self, value: object) -> tuple[int, int] | None:
        """读取可选输入尺寸。"""

        if isinstance(value, (list, tuple)) and len(value) == 2:
            return (int(value[0]), int(value[1]))
        return None

    def _read_optional_str(self, value: object) -> str | None:
        """读取可选字符串。"""

        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _read_optional_float(self, value: object) -> float | None:
        """读取可选浮点数。"""

        if value is None:
            return None
        return float(value)

    def _now_iso(self) -> str:
        """返回当前 UTC ISO 时间。"""

        return datetime.now(timezone.utc).isoformat()
