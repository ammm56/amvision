"""YOLO 主线 classification 训练任务适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.queue import QueueBackend
from backend.service.application.dataset_export_format_support import (
    require_supported_dataset_export_format,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
    Yolo11TrainingOutputRegistration,
)
from backend.service.application.models.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
    Yolo26TrainingOutputRegistration,
)
from backend.service.application.models.yolo_primary_classification_training import (
    YOLO_PRIMARY_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL,
    YOLO_PRIMARY_CLASSIFICATION_IMPLEMENTATION_MODE,
    YoloPrimaryClassificationTrainingControlCommand,
    YoloPrimaryClassificationTrainingEpochProgress,
    YoloPrimaryClassificationTrainingPausedError,
    YoloPrimaryClassificationTrainingSavePoint,
    YoloPrimaryClassificationTrainingTerminatedError,
    YoloPrimaryClassificationTrainingExecutionRequest,
    YoloPrimaryClassificationTrainingExecutionResult,
    run_yolo_primary_classification_training,
)
from backend.service.application.models.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8TrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND = "yolo-primary-classification-training"
YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME = "yolo-primary-classification-trainings"
YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY = "classification_training_control"

_CLASSIFICATION_MODEL_SERVICE_MAP: dict[str, tuple[type, type]] = {
    "yolov8": (SqlAlchemyYoloV8ModelService, YoloV8TrainingOutputRegistration),
    "yolo11": (SqlAlchemyYolo11ModelService, Yolo11TrainingOutputRegistration),
    "yolo26": (SqlAlchemyYolo26ModelService, Yolo26TrainingOutputRegistration),
}


@dataclass(frozen=True)
class YoloPrimaryClassificationTrainingTaskRequest:
    """描述一次 classification 训练任务创建请求。"""

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
    input_size: tuple[int, int] | None = None
    precision: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)
    display_name: str = ""
    model_type: str = "yolov8"


@dataclass(frozen=True)
class _ClassificationTrainingControlState:
    """描述 classification 训练控制状态快照。"""

    save_requested: bool = False
    pause_requested: bool = False
    terminate_requested: bool = False


class SqlAlchemyYoloPrimaryClassificationTrainingTaskService:
    """管理 YOLO 主线 classification 训练任务的完整生命周期。"""

    task_type = CLASSIFICATION_TASK_TYPE
    model_label = "YOLO primary classification"
    training_task_kind = YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND
    training_queue_name = YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        queue_backend: QueueBackend,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        self.session_factory = session_factory
        self.queue_backend = queue_backend
        self.dataset_storage = dataset_storage
        self.task_service = SqlAlchemyTaskService(session_factory=self.session_factory)

    def submit_training_task(
        self,
        request: YoloPrimaryClassificationTrainingTaskRequest,
        *,
        created_by: str | None = None,
    ) -> dict[str, object]:
        """创建 classification 训练任务并入队。"""

        model_type = self._normalize_model_type(request.model_type)
        dataset_export = self._resolve_dataset_export(
            project_id=request.project_id,
            dataset_export_id=request.dataset_export_id,
            dataset_export_manifest_key=request.dataset_export_manifest_key,
            model_type=model_type,
        )
        task_spec = self._build_task_spec(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
        )
        metadata = {
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_id": dataset_export.dataset_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "model_type": model_type,
            "task_type": CLASSIFICATION_TASK_TYPE,
            "output_model_name": request.output_model_name,
            "model_scale": request.model_scale,
            "queue_payload": dict(task_spec),
        }
        created_task = self.task_service.create_task(
            CreateTaskRequest(
                task_kind=self.training_task_kind,
                project_id=request.project_id,
                created_by=created_by,
                display_name=request.display_name or request.output_model_name,
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
            queue_task = self.queue_backend.enqueue(
                queue_name=self.training_queue_name,
                payload=queue_payload,
            )
        except Exception as exc:
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=created_task.task_id,
                    event_type="status",
                    message="classification training queue submission failed",
                    payload={
                        "state": "failed",
                        "error_message": str(exc),
                        "progress": {"stage": "failed"},
                        "finished_at": self._now_iso(),
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
                message="classification training queued",
                payload={
                    "state": "queued",
                    "metadata": {
                        "queue_name": self.training_queue_name,
                        "queue_task_id": queue_task.task_id,
                    },
                },
            )
        )
        return {
            "task_id": created_task.task_id,
            "status": "queued",
            "queue_name": self.training_queue_name,
            "queue_task_id": queue_task.task_id,
        }

    def process_training_task(
        self,
        task_record: TaskRecord,
        *,
        model_type: str,
        on_control_state_change: Callable[[_ClassificationTrainingControlState], None] | None = None,
    ) -> dict[str, object]:
        """执行 classification 训练工作负载。"""

        payload = self._read_task_payload(task_record)
        resolved_model_type = self._normalize_model_type(
            payload.get("model_type", model_type)
        )
        dataset_export = self._resolve_dataset_export(
            project_id=task_record.project_id,
            dataset_export_id=self._read_optional_str(payload.get("dataset_export_id")),
            dataset_export_manifest_key=self._read_optional_str(
                payload.get("dataset_export_manifest_key")
            ),
            model_type=resolved_model_type,
        )
        manifest_object_key = dataset_export.manifest_object_key
        if manifest_object_key is None or not manifest_object_key.strip():
            raise InvalidRequestError(
                "classification 训练任务缺少 manifest_object_key",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        manifest_payload = self.dataset_storage.read_json(manifest_object_key)
        if not isinstance(manifest_payload, dict):
            raise InvalidRequestError("classification 训练 manifest 无效")

        input_size = self._read_input_size(payload.get("input_size"))
        output_prefix = f"task-runs/{task_record.task_id}"
        temporary_latest_checkpoint_path = self.dataset_storage.resolve(
            f"{output_prefix}/latest-checkpoint.pt"
        )
        temporary_best_checkpoint_path = self.dataset_storage.resolve(
            f"{output_prefix}/best-checkpoint.pt"
        )
        latest_checkpoint_object_key = f"{output_prefix}/output-files/latest-checkpoint.pt"
        checkpoint_object_key = f"{output_prefix}/output-files/best-checkpoint.pt"
        train_metrics_object_key = f"{output_prefix}/output-files/train-metrics.json"
        validation_metrics_object_key = (
            f"{output_prefix}/output-files/validation-metrics.json"
        )
        labels_object_key = f"{output_prefix}/output-files/labels.txt"
        legacy_labels_json_object_key = f"{output_prefix}/output-files/labels.json"
        summary_object_key = f"{output_prefix}/output-files/training-summary.json"
        resume_checkpoint_path = self._resolve_resume_checkpoint_path(task_record)
        started_at = self._now_iso()
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_record.task_id,
                event_type="status",
                message="classification training started",
                payload={
                    "state": "running",
                    "started_at": started_at,
                    "progress": {
                        "stage": "running",
                        "task_type": CLASSIFICATION_TASK_TYPE,
                        "model_type": resolved_model_type,
                    },
                },
            )
        )

        control_state = self._read_control_state(task_record.task_id)

        def on_epoch(
            progress: YoloPrimaryClassificationTrainingEpochProgress,
        ) -> YoloPrimaryClassificationTrainingControlCommand | None:
            nonlocal control_state
            control_state = self._read_control_state(task_record.task_id)
            if on_control_state_change is not None:
                on_control_state_change(control_state)
            if control_state.terminate_requested:
                return YoloPrimaryClassificationTrainingControlCommand(
                    save_checkpoint=True,
                    terminate_training=True,
                )
            if control_state.pause_requested:
                return YoloPrimaryClassificationTrainingControlCommand(
                    save_checkpoint=True,
                    pause_training=True,
                )
            if control_state.save_requested:
                self._clear_manual_save_request(task_record.task_id)
                return YoloPrimaryClassificationTrainingControlCommand(
                    save_checkpoint=True
                )
            return None

        def on_savepoint(savepoint: YoloPrimaryClassificationTrainingSavePoint) -> None:
            self.dataset_storage.write_bytes(
                str(temporary_latest_checkpoint_path),
                savepoint.latest_checkpoint_bytes,
            )
            validation_accuracy = float(
                savepoint.validation_metrics.get("top1_accuracy", 0.0)
            )
            if validation_accuracy >= savepoint.best_metric_value:
                self.dataset_storage.write_bytes(
                    str(temporary_best_checkpoint_path),
                    savepoint.latest_checkpoint_bytes,
                )

        request = YoloPrimaryClassificationTrainingExecutionRequest(
            dataset_storage=self.dataset_storage,
            manifest_payload=manifest_payload,
            model_type=resolved_model_type,
            model_scale=str(payload.get("model_scale") or "nano"),
            batch_size=int(payload.get("batch_size") or 16),
            max_epochs=int(payload.get("max_epochs") or 30),
            evaluation_interval=int(
                payload.get("evaluation_interval")
                or YOLO_PRIMARY_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL
            ),
            input_size=input_size,
            precision=str(payload.get("precision") or "fp32"),
            resume_checkpoint_path=resume_checkpoint_path,
            extra_options=dict(payload.get("extra_options") or {}),
            epoch_callback=on_epoch,
            savepoint_callback=on_savepoint,
        )
        try:
            execution_result = run_yolo_primary_classification_training(request)
        except YoloPrimaryClassificationTrainingTerminatedError:
            cancelled_result = self._build_interrupted_result(
                status="cancelled",
                task_record=task_record,
                dataset_export=dataset_export,
                checkpoint_object_key=checkpoint_object_key,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
                output_prefix=output_prefix,
                train_metrics_object_key=train_metrics_object_key,
                validation_metrics_object_key=validation_metrics_object_key,
                labels_object_key=labels_object_key,
                summary_object_key=summary_object_key,
                finished_stage="cancelled",
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_record.task_id,
                    event_type="status",
                    message="classification training cancelled",
                    payload={
                        "state": "cancelled",
                        "finished_at": self._now_iso(),
                        "progress": {"stage": "cancelled"},
                        "metadata": {
                            YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY: {}
                        },
                        "result": cancelled_result,
                    },
                )
            )
            return cancelled_result
        except YoloPrimaryClassificationTrainingPausedError:
            paused_result = self._build_interrupted_result(
                status="paused",
                task_record=task_record,
                dataset_export=dataset_export,
                checkpoint_object_key=checkpoint_object_key,
                latest_checkpoint_object_key=latest_checkpoint_object_key,
                output_prefix=output_prefix,
                train_metrics_object_key=train_metrics_object_key,
                validation_metrics_object_key=validation_metrics_object_key,
                labels_object_key=labels_object_key,
                summary_object_key=summary_object_key,
                finished_stage="paused",
            )
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_record.task_id,
                    event_type="status",
                    message="classification training paused",
                    payload={
                        "state": "paused",
                        "progress": {"stage": "paused"},
                        "metadata": {
                            YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY: {}
                        },
                        "result": paused_result,
                    },
                )
            )
            return paused_result
        except Exception as exc:
            failed_result = {
                "status": "failed",
                "task_id": task_record.task_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "dataset_version_id": dataset_export.dataset_version_id,
                "format_id": dataset_export.format_id,
                "output_prefix": output_prefix,
                "task_type": CLASSIFICATION_TASK_TYPE,
                "model_type": resolved_model_type,
            }
            self.task_service.append_task_event(
                AppendTaskEventRequest(
                    task_id=task_record.task_id,
                    event_type="status",
                    message="classification training failed",
                    payload={
                        "state": "failed",
                        "finished_at": self._now_iso(),
                        "error_message": str(exc),
                        "progress": {"stage": "failed"},
                        "result": failed_result,
                    },
                )
            )
            raise

        self.dataset_storage.write_bytes(
            str(temporary_latest_checkpoint_path),
            execution_result.latest_checkpoint_bytes,
        )
        self.dataset_storage.write_bytes(
            latest_checkpoint_object_key,
            execution_result.latest_checkpoint_bytes,
        )
        best_checkpoint_bytes = execution_result.latest_checkpoint_bytes
        if temporary_best_checkpoint_path.is_file():
            best_checkpoint_bytes = temporary_best_checkpoint_path.read_bytes()
        else:
            self.dataset_storage.write_bytes(
                str(temporary_best_checkpoint_path),
                best_checkpoint_bytes,
            )
        self.dataset_storage.write_bytes(checkpoint_object_key, best_checkpoint_bytes)
        self.dataset_storage.write_json(
            train_metrics_object_key,
            execution_result.metrics_payload,
        )
        self.dataset_storage.write_json(
            validation_metrics_object_key,
            execution_result.validation_metrics_payload,
        )
        self._write_labels_text(
            labels_object_key=labels_object_key,
            labels=execution_result.labels,
        )
        self.dataset_storage.write_json(
            legacy_labels_json_object_key,
            {"labels": list(execution_result.labels)},
        )
        summary = self._build_training_summary(
            task_record=task_record,
            dataset_export=dataset_export,
            execution_result=execution_result,
            payload=payload,
            model_type=resolved_model_type,
            output_prefix=output_prefix,
            checkpoint_object_key=checkpoint_object_key,
            latest_checkpoint_object_key=latest_checkpoint_object_key,
            labels_object_key=labels_object_key,
            train_metrics_object_key=train_metrics_object_key,
            validation_metrics_object_key=validation_metrics_object_key,
            summary_object_key=summary_object_key,
        )
        model_version_id = self._register_training_output_model_version(
            task_record=task_record,
            dataset_export=dataset_export,
            payload=payload,
            model_type=resolved_model_type,
            execution_result=execution_result,
            checkpoint_object_key=checkpoint_object_key,
            labels_object_key=labels_object_key,
            train_metrics_object_key=train_metrics_object_key,
            summary=summary,
        )
        summary["model_version_id"] = model_version_id
        self.dataset_storage.write_json(summary_object_key, summary)
        task_result = {
            "status": "succeeded",
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "output_prefix": output_prefix,
            "output_object_prefix": output_prefix,
            "checkpoint_object_key": checkpoint_object_key,
            "latest_checkpoint_object_key": latest_checkpoint_object_key,
            "labels_object_key": labels_object_key,
            "metrics_object_key": train_metrics_object_key,
            "validation_metrics_object_key": validation_metrics_object_key,
            "summary_object_key": summary_object_key,
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "labels": list(execution_result.labels),
            "model_version_id": model_version_id,
            "summary": summary,
        }
        self.task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_record.task_id,
                event_type="result",
                message="classification training succeeded",
                payload={
                    "state": "succeeded",
                    "finished_at": self._now_iso(),
                    "progress": {"stage": "succeeded", "percent": 100.0},
                    "metadata": {
                        YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY: {}
                    },
                    "result": task_result,
                },
            )
        )
        return task_result

    def request_training_save(self, task_record: TaskRecord) -> None:
        """请求分类训练保存 checkpoint。"""

        self._set_control_flag(task_record, "save_requested", True)

    def request_training_pause(self, task_record: TaskRecord) -> None:
        """请求分类训练暂停。"""

        self._set_control_flag(task_record, "pause_requested", True)

    def request_training_terminate(self, task_record: TaskRecord) -> None:
        """请求分类训练终止。"""

        self._set_control_flag(task_record, "terminate_requested", True)

    def _normalize_model_type(self, model_type: object) -> str:
        """把模型分类名称规范化为受支持值。"""

        normalized = str(model_type or "yolov8").strip().lower()
        if normalized not in _CLASSIFICATION_MODEL_SERVICE_MAP:
            raise InvalidRequestError(
                "当前 classification 训练不支持指定模型分类",
                details={
                    "model_type": normalized,
                    "supported": tuple(_CLASSIFICATION_MODEL_SERVICE_MAP.keys()),
                },
            )
        return normalized

    def _build_task_spec(
        self,
        *,
        request: YoloPrimaryClassificationTrainingTaskRequest,
        dataset_export: DatasetExport,
        model_type: str,
    ) -> dict[str, object]:
        """构建 classification 训练任务规格快照。"""

        return {
            "project_id": request.project_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "recipe_id": request.recipe_id,
            "model_scale": request.model_scale,
            "output_model_name": request.output_model_name,
            "warm_start_model_version_id": request.warm_start_model_version_id,
            "evaluation_interval": request.evaluation_interval,
            "max_epochs": request.max_epochs,
            "batch_size": request.batch_size,
            "input_size": list(request.input_size) if request.input_size else None,
            "precision": request.precision,
            "extra_options": dict(request.extra_options),
            "model_type": model_type,
            "task_type": CLASSIFICATION_TASK_TYPE,
        }

    def _read_task_payload(self, task_record: TaskRecord) -> dict[str, object]:
        """从任务记录中解析训练负载。"""

        metadata = dict(task_record.metadata) if task_record.metadata else {}
        payload = metadata.get("queue_payload")
        if isinstance(payload, dict):
            return dict(payload)
        task_spec = dict(task_record.task_spec) if task_record.task_spec else {}
        if task_spec:
            return task_spec
        return metadata

    def _resolve_dataset_export(
        self,
        *,
        project_id: str,
        dataset_export_id: str | None,
        dataset_export_manifest_key: str | None,
        model_type: str,
    ) -> DatasetExport:
        """根据 id 或 manifest key 解析 classification 训练输入。"""

        export_by_id = None
        if dataset_export_id is not None:
            export_by_id = self._get_dataset_export(dataset_export_id)

        export_by_manifest = None
        if dataset_export_manifest_key is not None:
            export_by_manifest = self._get_dataset_export_by_manifest(
                dataset_export_manifest_key
            )

        dataset_export = export_by_id or export_by_manifest
        if dataset_export is None:
            raise ResourceNotFoundError("找不到可用于 classification 训练的 DatasetExport")
        if (
            export_by_id is not None
            and export_by_manifest is not None
            and export_by_id.dataset_export_id != export_by_manifest.dataset_export_id
        ):
            raise InvalidRequestError(
                "dataset_export_id 与 dataset_export_manifest_key 不属于同一个 DatasetExport",
                details={
                    "dataset_export_id": export_by_id.dataset_export_id,
                    "manifest_object_key": dataset_export_manifest_key,
                },
            )
        if dataset_export.project_id != project_id:
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
        if dataset_export.task_type != CLASSIFICATION_TASK_TYPE:
            raise InvalidRequestError(
                "当前 DatasetExport 不是 classification 导出",
                details={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "task_type": dataset_export.task_type,
                },
            )
        if dataset_export.manifest_object_key is None or not dataset_export.manifest_object_key.strip():
            raise InvalidRequestError(
                "当前 DatasetExport 缺少 manifest_object_key，不能用于训练",
                details={"dataset_export_id": dataset_export.dataset_export_id},
            )
        require_supported_dataset_export_format(
            model_type=model_type,
            task_type=CLASSIFICATION_TASK_TYPE,
            format_id=dataset_export.format_id,
            dataset_export_id=dataset_export.dataset_export_id,
            unsupported_message="当前 classification 训练只接受当前模型支持的 classification 导出格式",
        )
        return dataset_export

    def _get_dataset_export(self, dataset_export_id: str) -> DatasetExport:
        """按 id 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export(
                dataset_export_id
            )
        finally:
            unit_of_work.close()
        if dataset_export is None:
            raise ResourceNotFoundError(
                "找不到指定的 DatasetExport",
                details={"dataset_export_id": dataset_export_id},
            )
        return dataset_export

    def _get_dataset_export_by_manifest(
        self,
        manifest_object_key: str,
    ) -> DatasetExport:
        """按 manifest object key 读取一个 DatasetExport。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            dataset_export = (
                unit_of_work.dataset_exports.get_dataset_export_by_manifest_object_key(
                    manifest_object_key
                )
            )
        finally:
            unit_of_work.close()
        if dataset_export is None:
            raise ResourceNotFoundError(
                "找不到指定 manifest_object_key 对应的 DatasetExport",
                details={"manifest_object_key": manifest_object_key},
            )
        return dataset_export

    def _resolve_resume_checkpoint_path(self, task_record: TaskRecord) -> Path | None:
        """为 paused 的训练任务解析 resume checkpoint 路径。"""

        result = dict(task_record.result) if task_record.result else {}
        latest_checkpoint_object_key = self._read_optional_str(
            result.get("latest_checkpoint_object_key")
        )
        if latest_checkpoint_object_key is None:
            return None
        checkpoint_path = self.dataset_storage.resolve(latest_checkpoint_object_key)
        if checkpoint_path.is_file():
            return checkpoint_path
        return None

    def _build_training_summary(
        self,
        *,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        execution_result: YoloPrimaryClassificationTrainingExecutionResult,
        payload: dict[str, object],
        model_type: str,
        output_prefix: str,
        checkpoint_object_key: str,
        latest_checkpoint_object_key: str,
        labels_object_key: str,
        train_metrics_object_key: str,
        validation_metrics_object_key: str,
        summary_object_key: str,
    ) -> dict[str, object]:
        """构建 classification 训练摘要。"""

        input_size = self._read_input_size(payload.get("input_size"))
        training_config = {
            "recipe_id": self._read_optional_str(payload.get("recipe_id")) or "default",
            "model_type": model_type,
            "task_type": CLASSIFICATION_TASK_TYPE,
            "model_scale": str(payload.get("model_scale") or ""),
            "batch_size": int(payload.get("batch_size") or 16),
            "max_epochs": int(payload.get("max_epochs") or 30),
            "evaluation_interval": int(
                payload.get("evaluation_interval")
                or YOLO_PRIMARY_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL
            ),
            "input_size": list(input_size) if input_size is not None else None,
            "precision": str(payload.get("precision") or "fp32"),
            "extra_options": dict(payload.get("extra_options") or {}),
        }
        metrics_summary = {
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
        }
        output_files = {
            "checkpoint_object_key": checkpoint_object_key,
            "latest_checkpoint_object_key": latest_checkpoint_object_key,
            "labels_object_key": labels_object_key,
            "metrics_object_key": train_metrics_object_key,
            "validation_metrics_object_key": validation_metrics_object_key,
            "summary_object_key": summary_object_key,
        }
        return {
            "task_id": task_record.task_id,
            "task_type": CLASSIFICATION_TASK_TYPE,
            "model_type": model_type,
            "model_scale": str(payload.get("model_scale") or ""),
            "output_model_name": str(payload.get("output_model_name") or ""),
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "category_names": list(execution_result.labels),
            "input_size": list(input_size) if input_size is not None else None,
            "best_metric_name": execution_result.best_metric_name,
            "best_metric_value": execution_result.best_metric_value,
            "implementation_mode": YOLO_PRIMARY_CLASSIFICATION_IMPLEMENTATION_MODE,
            "training_config": training_config,
            "metrics_summary": metrics_summary,
            "output_files": output_files,
            "metrics_payload": execution_result.metrics_payload,
            "validation_metrics_payload": execution_result.validation_metrics_payload,
            "output_prefix": output_prefix,
        }

    def _register_training_output_model_version(
        self,
        *,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        payload: dict[str, object],
        model_type: str,
        execution_result: YoloPrimaryClassificationTrainingExecutionResult,
        checkpoint_object_key: str,
        labels_object_key: str,
        train_metrics_object_key: str,
        summary: dict[str, object],
    ) -> str:
        """把 classification 训练输出登记为 ModelVersion。"""

        service_cls, registration_cls = _CLASSIFICATION_MODEL_SERVICE_MAP[model_type]
        model_service = service_cls(session_factory=self.session_factory)
        return model_service.register_training_output(
            registration_cls(
                project_id=task_record.project_id,
                training_task_id=task_record.task_id,
                model_name=str(payload.get("output_model_name") or ""),
                model_scale=str(payload.get("model_scale") or ""),
                task_type=CLASSIFICATION_TASK_TYPE,
                dataset_version_id=dataset_export.dataset_version_id,
                checkpoint_file_id=f"{task_record.task_id}-checkpoint",
                checkpoint_file_uri=checkpoint_object_key,
                labels_file_id=f"{task_record.task_id}-labels",
                labels_file_uri=labels_object_key,
                metrics_file_id=f"{task_record.task_id}-metrics",
                metrics_file_uri=train_metrics_object_key,
                metadata={
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "manifest_object_key": dataset_export.manifest_object_key,
                    "category_names": list(execution_result.labels),
                    "input_size": summary.get("input_size"),
                    "training_config": dict(summary["training_config"]),
                    "metrics_summary": dict(summary["metrics_summary"]),
                    "output_files": dict(summary["output_files"]),
                    "registration_kind": "best-checkpoint",
                    "implementation_mode": YOLO_PRIMARY_CLASSIFICATION_IMPLEMENTATION_MODE,
                },
            )
        )

    def _build_interrupted_result(
        self,
        *,
        status: str,
        task_record: TaskRecord,
        dataset_export: DatasetExport,
        checkpoint_object_key: str,
        latest_checkpoint_object_key: str,
        output_prefix: str,
        train_metrics_object_key: str,
        validation_metrics_object_key: str,
        labels_object_key: str,
        summary_object_key: str,
        finished_stage: str,
    ) -> dict[str, object]:
        """构建 paused 或 cancelled 状态下的任务结果。"""

        if self.dataset_storage.resolve(f"{output_prefix}/latest-checkpoint.pt").is_file():
            self.dataset_storage.write_bytes(
                latest_checkpoint_object_key,
                self.dataset_storage.resolve(f"{output_prefix}/latest-checkpoint.pt").read_bytes(),
            )
        if self.dataset_storage.resolve(f"{output_prefix}/best-checkpoint.pt").is_file():
            self.dataset_storage.write_bytes(
                checkpoint_object_key,
                self.dataset_storage.resolve(f"{output_prefix}/best-checkpoint.pt").read_bytes(),
            )
        return {
            "status": status,
            "task_id": task_record.task_id,
            "dataset_export_id": dataset_export.dataset_export_id,
            "dataset_export_manifest_key": dataset_export.manifest_object_key,
            "dataset_version_id": dataset_export.dataset_version_id,
            "format_id": dataset_export.format_id,
            "output_prefix": output_prefix,
            "output_object_prefix": output_prefix,
            "checkpoint_object_key": checkpoint_object_key
            if self.dataset_storage.resolve(checkpoint_object_key).is_file()
            else None,
            "latest_checkpoint_object_key": latest_checkpoint_object_key
            if self.dataset_storage.resolve(latest_checkpoint_object_key).is_file()
            else None,
            "labels_object_key": labels_object_key
            if self.dataset_storage.resolve(labels_object_key).is_file()
            else None,
            "metrics_object_key": train_metrics_object_key
            if self.dataset_storage.resolve(train_metrics_object_key).is_file()
            else None,
            "validation_metrics_object_key": validation_metrics_object_key
            if self.dataset_storage.resolve(validation_metrics_object_key).is_file()
            else None,
            "summary_object_key": summary_object_key
            if self.dataset_storage.resolve(summary_object_key).is_file()
            else None,
            "task_type": CLASSIFICATION_TASK_TYPE,
            "progress_stage": finished_stage,
        }

    def _read_control_state(self, task_id: str) -> _ClassificationTrainingControlState:
        """从任务 metadata 中读取最新控制状态。"""

        task = self.task_service.get_task(task_id).task
        metadata = dict(task.metadata) if task.metadata else {}
        raw_control = metadata.get(YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY)
        if not isinstance(raw_control, dict):
            return _ClassificationTrainingControlState()
        return _ClassificationTrainingControlState(
            save_requested=bool(raw_control.get("save_requested") is True),
            pause_requested=bool(raw_control.get("pause_requested") is True),
            terminate_requested=bool(raw_control.get("terminate_requested") is True),
        )

    def _clear_manual_save_request(self, task_id: str) -> None:
        """清理一次性手动保存请求，避免重复触发。"""

        task = self.task_service.get_task(task_id).task
        metadata = dict(task.metadata) if task.metadata else {}
        raw_control = metadata.get(YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY)
        if not isinstance(raw_control, dict):
            return
        updated_control = dict(raw_control)
        updated_control["save_requested"] = False
        metadata[YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY] = updated_control
        self.task_service.update_task_metadata(task_id, metadata)

    def _set_control_flag(self, task_record: TaskRecord, flag: str, value: bool) -> None:
        """设置训练控制标记。"""

        metadata = dict(task_record.metadata) if task_record.metadata else {}
        control = metadata.get(YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY)
        if not isinstance(control, dict):
            control = {}
        control[flag] = value
        metadata[YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY] = control
        self.task_service.update_task_metadata(task_record.task_id, metadata)

    def _write_labels_text(
        self,
        *,
        labels_object_key: str,
        labels: tuple[str, ...],
    ) -> None:
        """按一行一个类别名写出 labels.txt。"""

        content = "\n".join(labels)
        if content:
            content = f"{content}\n"
        self.dataset_storage.write_text(labels_object_key, content)

    def _read_input_size(self, value: object) -> tuple[int, int] | None:
        """把输入尺寸负载解析为二元组。"""

        if isinstance(value, list | tuple) and len(value) == 2:
            return (int(value[0]), int(value[1]))
        return None

    def _read_optional_str(self, value: object) -> str | None:
        """读取可选字符串字段。"""

        if isinstance(value, str) and value.strip():
            return value
        return None

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 字符串。"""

        return datetime.now(timezone.utc).isoformat()
