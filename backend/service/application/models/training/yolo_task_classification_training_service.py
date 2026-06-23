"""YOLO 主线 classification 训练任务适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend.queue import QueueBackend
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.yolo_task_classification_training_dataset import (
    resolve_yolo_task_classification_training_dataset_export,
)
from backend.service.application.models.training.yolo_task_classification_training_events import (
    build_yolo_task_classification_training_cancelled_event,
    build_yolo_task_classification_training_failed_event,
    build_yolo_task_classification_training_paused_event,
    build_yolo_task_classification_training_queue_failed_event,
    build_yolo_task_classification_training_queued_event,
    build_yolo_task_classification_training_started_event,
    build_yolo_task_classification_training_succeeded_event,
)
from backend.service.application.models.training.yolo_task_classification_training_control import (
    YoloTaskClassificationTrainingControlState,
    build_yolo_task_classification_training_control_metadata,
    clear_yolo_task_classification_manual_save_request,
    read_yolo_task_classification_training_control_state,
)
from backend.service.application.models.training.yolo_task_classification_training_payload import (
    build_yolo_task_classification_training_create_task_metadata,
    build_yolo_task_classification_training_queue_payload,
    build_yolo_task_classification_training_task_spec,
    read_yolo_task_classification_training_payload,
)
from backend.service.application.models.training.yolo_task_classification_training_registration import (
    YOLO_TASK_CLASSIFICATION_MODEL_SERVICE_MAP,
    register_yolo_task_classification_training_output_model_version,
)
from backend.service.application.models.training.yolo_task_classification_training import (
    YOLO_TASK_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL,
    YOLO_TASK_CLASSIFICATION_IMPLEMENTATION_MODE,
    YoloTaskClassificationTrainingControlCommand,
    YoloTaskClassificationTrainingEpochProgress,
    YoloTaskClassificationTrainingPausedError,
    YoloTaskClassificationTrainingSavePoint,
    YoloTaskClassificationTrainingTerminatedError,
    YoloTaskClassificationTrainingExecutionRequest,
    YoloTaskClassificationTrainingExecutionResult,
    run_yolo_task_classification_training,
)
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO_TASK_CLASSIFICATION_TRAINING_TASK_KIND = "yolo-task-classification-training"
YOLO_TASK_CLASSIFICATION_TRAINING_QUEUE_NAME = (
    "yolo-task-classification-trainings"
)
YOLO_TASK_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY = (
    "classification_training_control"
)


@dataclass(frozen=True)
class YoloTaskClassificationTrainingRequest:
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


class SqlAlchemyYoloTaskClassificationTrainingService:
    """管理 YOLO 主线 classification 训练任务的完整生命周期。"""

    task_type = CLASSIFICATION_TASK_TYPE
    model_label = "YOLO task classification"
    training_task_kind = YOLO_TASK_CLASSIFICATION_TRAINING_TASK_KIND
    training_queue_name = YOLO_TASK_CLASSIFICATION_TRAINING_QUEUE_NAME

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
        request: YoloTaskClassificationTrainingRequest,
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
        metadata = self._build_create_task_metadata(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
            task_spec=task_spec,
        )
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
        queue_payload = self._build_queue_payload(
            task_id=created_task.task_id,
            task_kind=self.training_task_kind,
            task_spec=task_spec,
        )
        try:
            queue_task = self.queue_backend.enqueue(
                queue_name=self.training_queue_name,
                payload=queue_payload,
            )
        except Exception as exc:
            self.task_service.append_task_event(
                build_yolo_task_classification_training_queue_failed_event(
                    task_id=created_task.task_id,
                    error_message=str(exc),
                    finished_at=self._now_iso(),
                    dataset_export_id=dataset_export.dataset_export_id,
                    dataset_export_manifest_key=dataset_export.manifest_object_key,
                )
            )
            raise
        self.task_service.append_task_event(
            build_yolo_task_classification_training_queued_event(
                task_id=created_task.task_id,
                queue_name=self.training_queue_name,
                queue_task_id=queue_task.task_id,
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
        on_control_state_change: Callable[
            [YoloTaskClassificationTrainingControlState],
            None,
        ]
        | None = None,
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
        latest_checkpoint_object_key = (
            f"{output_prefix}/output-files/latest-checkpoint.pt"
        )
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
            build_yolo_task_classification_training_started_event(
                task_id=task_record.task_id,
                started_at=started_at,
                model_type=resolved_model_type,
            )
        )

        control_state = self._read_control_state(task_record.task_id)

        def on_epoch(
            progress: YoloTaskClassificationTrainingEpochProgress,
        ) -> YoloTaskClassificationTrainingControlCommand | None:
            nonlocal control_state
            control_state = self._read_control_state(task_record.task_id)
            if on_control_state_change is not None:
                on_control_state_change(control_state)
            if control_state.terminate_requested:
                return YoloTaskClassificationTrainingControlCommand(
                    save_checkpoint=True,
                    terminate_training=True,
                )
            if control_state.pause_requested:
                return YoloTaskClassificationTrainingControlCommand(
                    save_checkpoint=True,
                    pause_training=True,
                )
            if control_state.save_requested:
                self._clear_manual_save_request(task_record.task_id)
                return YoloTaskClassificationTrainingControlCommand(
                    save_checkpoint=True
                )
            return None

        def on_savepoint(savepoint: YoloTaskClassificationTrainingSavePoint) -> None:
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

        request = YoloTaskClassificationTrainingExecutionRequest(
            dataset_storage=self.dataset_storage,
            manifest_payload=manifest_payload,
            model_type=resolved_model_type,
            model_scale=str(payload.get("model_scale") or "nano"),
            batch_size=int(payload.get("batch_size") or 16),
            max_epochs=int(payload.get("max_epochs") or 30),
            evaluation_interval=int(
                payload.get("evaluation_interval")
                or YOLO_TASK_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL
            ),
            input_size=input_size,
            precision=str(payload.get("precision") or "fp32"),
            resume_checkpoint_path=resume_checkpoint_path,
            extra_options=dict(payload.get("extra_options") or {}),
            epoch_callback=on_epoch,
            savepoint_callback=on_savepoint,
        )
        try:
            execution_result = self._run_training_execution(request)
        except self._terminated_error_types():
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
                build_yolo_task_classification_training_cancelled_event(
                    task_id=task_record.task_id,
                    finished_at=self._now_iso(),
                    result=cancelled_result,
                    control_metadata_key=YOLO_TASK_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
                )
            )
            return cancelled_result
        except self._paused_error_types():
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
                build_yolo_task_classification_training_paused_event(
                    task_id=task_record.task_id,
                    result=paused_result,
                    control_metadata_key=YOLO_TASK_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
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
                build_yolo_task_classification_training_failed_event(
                    task_id=task_record.task_id,
                    finished_at=self._now_iso(),
                    error_message=str(exc),
                    result=failed_result,
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
            build_yolo_task_classification_training_succeeded_event(
                task_id=task_record.task_id,
                finished_at=self._now_iso(),
                result=task_result,
                control_metadata_key=YOLO_TASK_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
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
        if normalized not in YOLO_TASK_CLASSIFICATION_MODEL_SERVICE_MAP:
            raise InvalidRequestError(
                "当前 classification 训练不支持指定模型分类",
                details={
                    "model_type": normalized,
                    "supported": tuple(
                        YOLO_TASK_CLASSIFICATION_MODEL_SERVICE_MAP.keys()
                    ),
                },
            )
        return normalized

    def _build_task_spec(
        self,
        *,
        request: YoloTaskClassificationTrainingRequest,
        dataset_export: DatasetExport,
        model_type: str,
    ) -> dict[str, object]:
        """构建 classification 训练任务规格快照。"""

        return build_yolo_task_classification_training_task_spec(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
        )

    def _build_create_task_metadata(
        self,
        *,
        request: YoloTaskClassificationTrainingRequest,
        dataset_export: DatasetExport,
        model_type: str,
        task_spec: dict[str, object],
    ) -> dict[str, object]:
        """构建 classification 训练 TaskRecord metadata。"""

        return build_yolo_task_classification_training_create_task_metadata(
            request=request,
            dataset_export=dataset_export,
            model_type=model_type,
            task_spec=task_spec,
        )

    def _build_queue_payload(
        self,
        *,
        task_id: str,
        task_kind: str,
        task_spec: dict[str, object],
    ) -> dict[str, object]:
        """构建 classification 训练队列负载。"""

        return build_yolo_task_classification_training_queue_payload(
            task_id=task_id,
            task_kind=task_kind,
            task_spec=task_spec,
        )

    def _read_task_payload(self, task_record: TaskRecord) -> dict[str, object]:
        """从任务记录中解析训练负载。"""

        return read_yolo_task_classification_training_payload(task_record)

    def _run_training_execution(
        self,
        request: YoloTaskClassificationTrainingExecutionRequest,
    ) -> YoloTaskClassificationTrainingExecutionResult:
        """执行 primary classification 训练。"""

        return run_yolo_task_classification_training(request)

    @staticmethod
    def _terminated_error_types() -> tuple[type[BaseException], ...]:
        """返回应按取消处理的训练异常类型。"""

        return (YoloTaskClassificationTrainingTerminatedError,)

    @staticmethod
    def _paused_error_types() -> tuple[type[BaseException], ...]:
        """返回应按暂停处理的训练异常类型。"""

        return (YoloTaskClassificationTrainingPausedError,)

    def _resolve_dataset_export(
        self,
        *,
        project_id: str,
        dataset_export_id: str | None,
        dataset_export_manifest_key: str | None,
        model_type: str,
    ) -> DatasetExport:
        """根据 id 或 manifest key 解析 classification 训练输入。"""

        return resolve_yolo_task_classification_training_dataset_export(
            session_factory=self.session_factory,
            project_id=project_id,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
            model_type=model_type,
        )

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
        execution_result: YoloTaskClassificationTrainingExecutionResult,
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
                or YOLO_TASK_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL
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
            "implementation_mode": self._resolve_implementation_mode(model_type),
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
        execution_result: YoloTaskClassificationTrainingExecutionResult,
        checkpoint_object_key: str,
        labels_object_key: str,
        train_metrics_object_key: str,
        summary: dict[str, object],
    ) -> str:
        """把 classification 训练输出登记为 ModelVersion。"""

        return register_yolo_task_classification_training_output_model_version(
            session_factory=self.session_factory,
            task_record=task_record,
            dataset_export=dataset_export,
            payload=payload,
            model_type=model_type,
            execution_result=execution_result,
            checkpoint_object_key=checkpoint_object_key,
            labels_object_key=labels_object_key,
            train_metrics_object_key=train_metrics_object_key,
            summary=summary,
        )

    @staticmethod
    def _resolve_implementation_mode(model_type: str) -> str:
        """按模型分类返回 classification 训练实现标记。"""

        return YOLO_TASK_CLASSIFICATION_IMPLEMENTATION_MODE

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

        if self.dataset_storage.resolve(
            f"{output_prefix}/latest-checkpoint.pt"
        ).is_file():
            self.dataset_storage.write_bytes(
                latest_checkpoint_object_key,
                self.dataset_storage.resolve(
                    f"{output_prefix}/latest-checkpoint.pt"
                ).read_bytes(),
            )
        if self.dataset_storage.resolve(
            f"{output_prefix}/best-checkpoint.pt"
        ).is_file():
            self.dataset_storage.write_bytes(
                checkpoint_object_key,
                self.dataset_storage.resolve(
                    f"{output_prefix}/best-checkpoint.pt"
                ).read_bytes(),
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

    def _read_control_state(
        self, task_id: str
    ) -> YoloTaskClassificationTrainingControlState:
        """从任务 metadata 中读取最新控制状态。"""

        task = self.task_service.get_task(task_id).task
        metadata = dict(task.metadata) if task.metadata else {}
        return read_yolo_task_classification_training_control_state(
            metadata=metadata,
            control_metadata_key=YOLO_TASK_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
        )

    def _clear_manual_save_request(self, task_id: str) -> None:
        """清理一次性手动保存请求，避免重复触发。"""

        task = self.task_service.get_task(task_id).task
        metadata = dict(task.metadata) if task.metadata else {}
        updated_metadata = clear_yolo_task_classification_manual_save_request(
            metadata=metadata,
            control_metadata_key=YOLO_TASK_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
        )
        if updated_metadata is None:
            return
        self.task_service.update_task_metadata(task_id, updated_metadata)

    def _set_control_flag(
        self, task_record: TaskRecord, flag: str, value: bool
    ) -> None:
        """设置训练控制标记。"""

        metadata = dict(task_record.metadata) if task_record.metadata else {}
        updated_metadata = build_yolo_task_classification_training_control_metadata(
            metadata=metadata,
            control_metadata_key=YOLO_TASK_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
            flag=flag,
            value=value,
        )
        self.task_service.update_task_metadata(task_record.task_id, updated_metadata)

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
