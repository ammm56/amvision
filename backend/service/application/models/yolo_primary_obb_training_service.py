"""YOLO 主线 OBB 训练任务适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.queue import QueueBackend
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_primary_obb_training import (
    YoloPrimaryObbTrainingExecutionRequest,
    YoloPrimaryObbTrainingExecutionResult,
    YoloPrimaryObbTrainingPausedError,
    YoloPrimaryObbTrainingTerminatedError,
    run_yolo_primary_obb_training,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, CreateTaskRequest
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


OBB_TRAINING_TASK_KIND = "obb-training"
OBB_TRAINING_QUEUE_NAME = "obb-trainings"
OBB_TRAINING_CONTROL_METADATA_KEY = "obb_training_control"


@dataclass(frozen=True)
class YoloPrimaryObbTrainingTaskRequest:
    """描述一次 OBB 训练任务创建请求。"""

    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    input_size: tuple[int, int] | None = None
    precision: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)
    display_name: str = ""


class SqlAlchemyYoloPrimaryObbTrainingTaskService:
    """管理 YOLO 主线 OBB 训练任务的完整生命周期。"""

    def __init__(self, *, session_factory: SessionFactory, queue_backend: QueueBackend, dataset_storage: LocalDatasetStorage) -> None:
        self.session_factory = session_factory
        self.queue_backend = queue_backend
        self.dataset_storage = dataset_storage

    def submit_training_task(self, request: YoloPrimaryObbTrainingTaskRequest, *, created_by: str | None = None) -> dict[str, object]:
        """创建 OBB 训练任务并入队。"""
        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task = task_service.create_task(CreateTaskRequest(
            task_kind=OBB_TRAINING_TASK_KIND, project_id=request.project_id,
            created_by=created_by, display_name=request.display_name or request.output_model_name,
            metadata={"model_scale": request.model_scale, "output_model_name": request.output_model_name, "task_type": OBB_TASK_TYPE},
        ))
        queue_task = self.queue_backend.enqueue(queue_name=OBB_TRAINING_QUEUE_NAME, payload={
            "task_id": task.task_id, "task_kind": OBB_TRAINING_TASK_KIND,
            "project_id": request.project_id, "recipe_id": request.recipe_id,
            "model_scale": request.model_scale, "output_model_name": request.output_model_name,
            "dataset_export_id": request.dataset_export_id,
            "dataset_export_manifest_key": request.dataset_export_manifest_key,
            "max_epochs": request.max_epochs, "batch_size": request.batch_size,
            "input_size": list(request.input_size) if request.input_size else None,
            "precision": request.precision, "extra_options": request.extra_options,
        })
        return {"task_id": task.task_id, "status": task.status, "queue_name": OBB_TRAINING_QUEUE_NAME, "queue_task_id": queue_task.task_id}

    def process_training_task(self, task_record: TaskRecord, *, model_type: str) -> dict[str, object]:
        """执行 OBB 训练工作负载。"""
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
            raise InvalidRequestError("obb 训练任务缺少 dataset_export_id 或 manifest_key")
        manifest = self.dataset_storage.read_json(mk)
        if not isinstance(manifest, dict):
            raise InvalidRequestError("obb 训练 manifest 无效")
        input_size = None
        raw_is = payload.get("input_size")
        if isinstance(raw_is, list) and len(raw_is) == 2:
            input_size = (int(raw_is[0]), int(raw_is[1]))
        op = f"task-runs/{task_record.task_id}"
        latest = self.dataset_storage.resolve(f"{op}/latest-checkpoint.pt")

        def on_sp(sv) -> None:
            self.dataset_storage.write_bytes(str(latest), sv.latest_checkpoint_bytes)

        try:
            result = run_yolo_primary_obb_training(YoloPrimaryObbTrainingExecutionRequest(
                dataset_storage=self.dataset_storage, manifest_payload=manifest,
                model_type=model_type, model_scale=str(payload.get("model_scale", "nano")),
                batch_size=int(payload.get("batch_size") or 1),
                max_epochs=int(payload.get("max_epochs") or 1),
                input_size=input_size, precision=str(payload.get("precision") or "fp32"),
                extra_options=payload.get("extra_options", {}),
                savepoint_callback=on_sp,
            ))
        except YoloPrimaryObbTrainingTerminatedError:
            return {"status": "terminated", "task_id": task_record.task_id}
        except YoloPrimaryObbTrainingPausedError:
            return {"status": "paused", "task_id": task_record.task_id}

        self.dataset_storage.write_json(f"{op}/output-files/train-metrics.json", result.metrics_payload)
        self.dataset_storage.write_json(f"{op}/output-files/labels.json", {"labels": list(result.labels)})
        return {"status": "completed", "task_id": task_record.task_id, "output_prefix": op, "labels": list(result.labels)}

    def request_training_save(self, task_record: TaskRecord) -> None:
        """请求 OBB 训练保存 checkpoint。"""
        self._set_control_flag(task_record, "save_requested", True)

    def request_training_pause(self, task_record: TaskRecord) -> None:
        """请求 OBB 训练暂停。"""
        self._set_control_flag(task_record, "pause_requested", True)

    def request_training_terminate(self, task_record: TaskRecord) -> None:
        """请求 OBB 训练终止。"""
        self._set_control_flag(task_record, "terminate_requested", True)

    def _set_control_flag(self, task_record: TaskRecord, flag: str, value: bool) -> None:
        metadata = dict(task_record.metadata) if task_record.metadata else {}
        control = metadata.get(OBB_TRAINING_CONTROL_METADATA_KEY)
        if not isinstance(control, dict):
            control = {}
        control[flag] = value
        metadata[OBB_TRAINING_CONTROL_METADATA_KEY] = control
        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task_service.update_task_metadata(task_record.task_id, metadata)
