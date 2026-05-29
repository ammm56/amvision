"""YOLO 主线 classification 训练任务适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.queue import QueueBackend
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolo_primary_classification_training import (
    YOLO_PRIMARY_CLASSIFICATION_IMPLEMENTATION_MODE,
    YOLO_PRIMARY_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL,
    YoloPrimaryClassificationTrainingExecutionRequest,
    YoloPrimaryClassificationTrainingExecutionResult,
    YoloPrimaryClassificationTrainingBatchProgress,
    YoloPrimaryClassificationTrainingControlCommand,
    YoloPrimaryClassificationTrainingEpochProgress,
    YoloPrimaryClassificationTrainingPausedError,
    YoloPrimaryClassificationTrainingSavePoint,
    YoloPrimaryClassificationTrainingTerminatedError,
    run_yolo_primary_classification_training,
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


@dataclass(frozen=True)
class YoloPrimaryClassificationTrainingTaskRequest:
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


@dataclass(frozen=True)
class _ClassificationTrainingControlState:
    save_requested: bool = False
    pause_requested: bool = False
    terminate_requested: bool = False


class SqlAlchemyYoloPrimaryClassificationTrainingTaskService:
    """管理 YOLO 主线 classification 训练任务的完整生命周期。"""

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

    def submit_training_task(
        self,
        request: YoloPrimaryClassificationTrainingTaskRequest,
        *,
        created_by: str | None = None,
    ) -> dict[str, object]:
        """创建分类训练任务并入队。"""

        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task = task_service.create_task(
            CreateTaskRequest(
                task_kind=YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND,
                project_id=request.project_id,
                created_by=created_by,
                display_name=request.display_name or request.output_model_name,
                metadata={
                    "model_scale": request.model_scale,
                    "output_model_name": request.output_model_name,
                    "task_type": CLASSIFICATION_TASK_TYPE,
                },
            )
        )
        queue_task_id = self.queue_backend.submit_task(
            YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
            json_payload={
                "task_id": task.task_id,
                "task_kind": YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND,
                "project_id": request.project_id,
                "recipe_id": request.recipe_id,
                "model_scale": request.model_scale,
                "output_model_name": request.output_model_name,
                "dataset_export_id": request.dataset_export_id,
                "dataset_export_manifest_key": request.dataset_export_manifest_key,
                "warm_start_model_version_id": request.warm_start_model_version_id,
                "evaluation_interval": request.evaluation_interval,
                "max_epochs": request.max_epochs,
                "batch_size": request.batch_size,
                "input_size": list(request.input_size) if request.input_size else None,
                "precision": request.precision,
                "extra_options": request.extra_options,
            },
        )
        return {
            "task_id": task.task_id,
            "status": task.status,
            "queue_name": YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
            "queue_task_id": queue_task_id,
        }

    def process_training_task(
        self,
        task_record: TaskRecord,
        *,
        model_type: str,
        on_control_state_change: Callable[[_ClassificationTrainingControlState], None] | None = None,
    ) -> dict[str, object]:
        """执行 classification 训练工作负载。"""

        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        metadata = task_record.metadata or {}
        payload = metadata.get("queue_payload", {})
        if not payload:
            with SqlAlchemyUnitOfWork(self.session_factory) as uow:
                task = uow.tasks.get(task_record.task_id)
                if task is not None:
                    payload = task.metadata or {}
        dataset_export_id = payload.get("dataset_export_id")
        manifest_key = payload.get("dataset_export_manifest_key")
        if not dataset_export_id or not manifest_key:
            raise InvalidRequestError("classification 训练任务缺少 dataset_export_id 或 manifest_key")
        manifest_payload = self.dataset_storage.read_json(manifest_key)
        if not isinstance(manifest_payload, dict):
            raise InvalidRequestError("classification 训练 manifest 无效")

        input_size = None
        raw_input_size = payload.get("input_size")
        if isinstance(raw_input_size, list) and len(raw_input_size) == 2:
            input_size = (int(raw_input_size[0]), int(raw_input_size[1]))

        output_prefix = f"task-runs/{task_record.task_id}"
        best_checkpoint_path = self.dataset_storage.resolve(f"{output_prefix}/best-checkpoint.pt")
        latest_checkpoint_path = self.dataset_storage.resolve(f"{output_prefix}/latest-checkpoint.pt")

        eval_interval = int(payload.get("evaluation_interval") or YOLO_PRIMARY_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL)
        control_state = _ClassificationTrainingControlState()

        def on_epoch(progress: YoloPrimaryClassificationTrainingEpochProgress) -> YoloPrimaryClassificationTrainingControlCommand | None:
            if on_control_state_change is not None:
                on_control_state_change(control_state)
            if control_state.terminate_requested:
                return YoloPrimaryClassificationTrainingControlCommand(terminate_training=True)
            if control_state.pause_requested:
                return YoloPrimaryClassificationTrainingControlCommand(save_checkpoint=True, pause_training=True)
            if control_state.save_requested:
                control_state.save_requested = False
                return YoloPrimaryClassificationTrainingControlCommand(save_checkpoint=True)
            return None

        def on_savepoint(savepoint: YoloPrimaryClassificationTrainingSavePoint) -> None:
            self.dataset_storage.write_bytes(str(latest_checkpoint_path), savepoint.latest_checkpoint_bytes)
            if savepoint.validation_metrics:
                val_metric = float(savepoint.validation_metrics.get("top1_accuracy", 0.0))
                if val_metric >= savepoint.best_metric_value:
                    self.dataset_storage.write_bytes(str(best_checkpoint_path), savepoint.latest_checkpoint_bytes)

        executor = lambda: run_yolo_primary_classification_training(
            YoloPrimaryClassificationTrainingExecutionRequest(
                dataset_storage=self.dataset_storage,
                manifest_payload=manifest_payload,
                model_type=model_type,
                model_scale=str(payload.get("model_scale", "nano")),
                batch_size=int(payload.get("batch_size") or 16),
                max_epochs=int(payload.get("max_epochs") or 30),
                evaluation_interval=eval_interval,
                input_size=input_size,
                precision=str(payload.get("precision") or "fp32"),
                extra_options=payload.get("extra_options", {}),
                epoch_callback=on_epoch,
                savepoint_callback=on_savepoint,
            )
        )
        try:
            result = executor()
        except YoloPrimaryClassificationTrainingTerminatedError:
            return {"status": "terminated", "task_id": task_record.task_id}
        except YoloPrimaryClassificationTrainingPausedError:
            return {"status": "paused", "task_id": task_record.task_id}
        except Exception as exc:
            raise

        if best_checkpoint_path.is_file():
            self.dataset_storage.write_bytes(
                f"{output_prefix}/output-files/best-checkpoint.pt",
                best_checkpoint_path.read_bytes(),
            )
        train_metrics_path = f"{output_prefix}/output-files/train-metrics.json"
        self.dataset_storage.write_json(train_metrics_path, result.metrics_payload)
        val_metrics_path = f"{output_prefix}/output-files/validation-metrics.json"
        self.dataset_storage.write_json(val_metrics_path, result.validation_metrics_payload)
        labels_path = f"{output_prefix}/output-files/labels.json"
        self.dataset_storage.write_json(labels_path, {"labels": list(result.labels)})

        return {
            "status": "completed",
            "task_id": task_record.task_id,
            "best_metric_name": result.best_metric_name,
            "best_metric_value": result.best_metric_value,
            "output_prefix": output_prefix,
            "labels": list(result.labels),
        }

    def request_training_save(self, task_record: TaskRecord) -> None:
        """请求分类训练保存 checkpoint。"""

        metadata = dict(task_record.metadata) if task_record.metadata else {}
        control = metadata.get(YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY)
        if isinstance(control, dict):
            control["save_requested"] = True
        else:
            control = {"save_requested": True}
        metadata[YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY] = control
        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task_service.update_task_metadata(task_record.task_id, metadata)

    def request_training_pause(self, task_record: TaskRecord) -> None:
        """请求分类训练暂停。"""

        metadata = dict(task_record.metadata) if task_record.metadata else {}
        control = metadata.get(YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY)
        if isinstance(control, dict):
            control["pause_requested"] = True
        else:
            control = {"pause_requested": True}
        metadata[YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY] = control
        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task_service.update_task_metadata(task_record.task_id, metadata)

    def request_training_terminate(self, task_record: TaskRecord) -> None:
        """请求分类训练终止。"""

        metadata = dict(task_record.metadata) if task_record.metadata else {}
        control = metadata.get(YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY)
        if isinstance(control, dict):
            control["terminate_requested"] = True
        else:
            control = {"terminate_requested": True}
        metadata[YOLO_PRIMARY_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY] = control
        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task_service.update_task_metadata(task_record.task_id, metadata)
