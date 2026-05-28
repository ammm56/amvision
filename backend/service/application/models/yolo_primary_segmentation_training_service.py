"""YOLO 主线 segmentation 训练任务适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from backend.queue import QueueBackend
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_primary_segmentation_training import (
    YOLO_PRIMARY_SEGMENTATION_IMPLEMENTATION_MODE,
    YoloPrimarySegmentationTrainingExecutionRequest,
    YoloPrimarySegmentationTrainingExecutionResult,
    YoloPrimarySegmentationTrainingEpochProgress,
    YoloPrimarySegmentationTrainingControlCommand,
    YoloPrimarySegmentationTrainingPausedError,
    YoloPrimarySegmentationTrainingSavePoint,
    YoloPrimarySegmentationTrainingTerminatedError,
    run_yolo_primary_segmentation_training,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, CreateTaskRequest
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND = "yolo-primary-segmentation-training"
YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME = "yolo-primary-segmentation-trainings"


@dataclass(frozen=True)
class YoloPrimarySegmentationTrainingTaskRequest:
    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    input_size: tuple[int, int] | None = None
    precision: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)
    display_name: str = ""


class SqlAlchemyYoloPrimarySegmentationTrainingTaskService:
    """管理 YOLO 主线 segmentation 训练任务的完整生命周期。"""

    def __init__(self, *, session_factory: SessionFactory, queue_backend: QueueBackend, dataset_storage: LocalDatasetStorage) -> None:
        self.session_factory = session_factory
        self.queue_backend = queue_backend
        self.dataset_storage = dataset_storage

    def submit_training_task(self, request: YoloPrimarySegmentationTrainingTaskRequest, *, created_by: str | None = None) -> dict[str, object]:
        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task = task_service.create_task(CreateTaskRequest(
            task_kind=YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND, project_id=request.project_id,
            created_by=created_by, display_name=request.display_name or request.output_model_name,
            metadata={"model_scale": request.model_scale, "output_model_name": request.output_model_name, "task_type": SEGMENTATION_TASK_TYPE},
        ))
        qtid = self.queue_backend.submit_task(YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME, json_payload={
            "task_id": task.task_id, "task_kind": YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND,
            "project_id": request.project_id, "recipe_id": request.recipe_id,
            "model_scale": request.model_scale, "output_model_name": request.output_model_name,
            "dataset_export_id": request.dataset_export_id,
            "dataset_export_manifest_key": request.dataset_export_manifest_key,
            "evaluation_interval": request.evaluation_interval, "max_epochs": request.max_epochs,
            "batch_size": request.batch_size, "input_size": list(request.input_size) if request.input_size else None,
            "precision": request.precision, "extra_options": request.extra_options,
        })
        return {"task_id": task.task_id, "status": task.status, "queue_name": YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME, "queue_task_id": qtid}

    def process_training_task(self, task_record: TaskRecord, *, model_type: str) -> dict[str, object]:
        meta = task_record.metadata or {}
        payload = meta.get("queue_payload", {})
        if not payload:
            from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
            with SqlAlchemyUnitOfWork(self.session_factory) as uow:
                t = uow.tasks.get(task_record.task_id)
                if t is not None:
                    payload = t.metadata or {}
        deid = payload.get("dataset_export_id")
        mk = payload.get("dataset_export_manifest_key")
        if not deid or not mk:
            raise InvalidRequestError("segmentation 训练任务缺少 dataset_export_id 或 manifest_key")
        manifest = self.dataset_storage.read_json(mk)
        if not isinstance(manifest, dict):
            raise InvalidRequestError("segmentation 训练 manifest 无效")
        input_size = None
        raw_is = payload.get("input_size")
        if isinstance(raw_is, list) and len(raw_is) == 2:
            input_size = (int(raw_is[0]), int(raw_is[1]))
        op = f"task-runs/{task_record.task_id}"
        latest = self.dataset_storage.resolve(f"{op}/latest-checkpoint.pt")
        best = self.dataset_storage.resolve(f"{op}/best-checkpoint.pt")

        def on_sp(sv: YoloPrimarySegmentationTrainingSavePoint) -> None:
            self.dataset_storage.write_bytes(str(latest), sv.latest_checkpoint_bytes)
            vm = sv.validation_metrics.get("map50_95", 0.0)
            if float(vm) >= sv.best_metric_value:
                self.dataset_storage.write_bytes(str(best), sv.latest_checkpoint_bytes)

        def on_ep(progress: YoloPrimarySegmentationTrainingEpochProgress) -> YoloPrimarySegmentationTrainingControlCommand | None:
            return YoloPrimarySegmentationTrainingControlCommand(save_checkpoint=True)

        try:
            result = run_yolo_primary_segmentation_training(YoloPrimarySegmentationTrainingExecutionRequest(
                dataset_storage=self.dataset_storage, manifest_payload=manifest,
                model_type=model_type, model_scale=str(payload.get("model_scale", "n")),
                batch_size=int(payload.get("batch_size") or 1), max_epochs=int(payload.get("max_epochs") or 1),
                evaluation_interval=int(payload.get("evaluation_interval") or 5),
                input_size=input_size, precision=str(payload.get("precision") or "fp32"),
                extra_options=payload.get("extra_options", {}),
                epoch_callback=on_ep, savepoint_callback=on_sp,
            ))
        except YoloPrimarySegmentationTrainingTerminatedError:
            return {"status": "terminated", "task_id": task_record.task_id}
        except YoloPrimarySegmentationTrainingPausedError:
            return {"status": "paused", "task_id": task_record.task_id}

        if best.is_file():
            self.dataset_storage.write_bytes(f"{op}/output-files/best-checkpoint.pt", best.read_bytes())
        self.dataset_storage.write_json(f"{op}/output-files/train-metrics.json", result.metrics_payload)
        self.dataset_storage.write_json(f"{op}/output-files/validation-metrics.json", result.validation_metrics_payload)
        self.dataset_storage.write_json(f"{op}/output-files/labels.json", {"labels": list(result.labels)})
        return {"status": "completed", "task_id": task_record.task_id, "best_metric_name": result.best_metric_name, "best_metric_value": result.best_metric_value, "output_prefix": op, "labels": list(result.labels)}
