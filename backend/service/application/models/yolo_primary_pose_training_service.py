"""pose 训练任务服务（薄入口）。"""

from backend.service.application.models.yolo_primary_pose_training import (
    YoloPrimaryPoseTrainingExecutionRequest,
    YoloPrimaryPoseTrainingExecutionResult,
    run_yolo_primary_pose_training,
    YoloPrimaryPoseTrainingPausedError,
    YoloPrimaryPoseTrainingTerminatedError,
    YoloPrimaryPoseTrainingSavePoint,
)
from backend.queue import QueueBackend
from backend.service.application.errors import InvalidRequestError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, CreateTaskRequest
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

POSE_TRAINING_TASK_KIND = "yolo-primary-pose-training"
POSE_TRAINING_QUEUE_NAME = "yolo-primary-pose-trainings"

class SqlAlchemyPoseTrainingTaskService:
    def __init__(self, *, session_factory: SessionFactory, queue_backend: QueueBackend, dataset_storage: LocalDatasetStorage):
        self.sf, self.qb, self.ds = session_factory, queue_backend, dataset_storage

    def submit(self, *, project_id, recipe_id, model_scale, output_model_name, dataset_export_id=None, dataset_export_manifest_key=None, max_epochs=None, batch_size=None, input_size=None, precision=None, extra_options=None, display_name="", created_by=None):
        ts = SqlAlchemyTaskService(session_factory=self.sf)
        t = ts.create_task(CreateTaskRequest(task_kind=POSE_TRAINING_TASK_KIND, project_id=project_id, created_by=created_by, display_name=display_name or output_model_name, metadata={"model_scale": model_scale, "output_model_name": output_model_name, "task_type": POSE_TASK_TYPE}))
        qid = self.qb.submit_task(POSE_TRAINING_QUEUE_NAME, json_payload={"task_id": t.task_id, "task_kind": POSE_TRAINING_TASK_KIND, "project_id": project_id, "recipe_id": recipe_id, "model_scale": model_scale, "output_model_name": output_model_name, "dataset_export_id": dataset_export_id, "dataset_export_manifest_key": dataset_export_manifest_key, "max_epochs": max_epochs, "batch_size": batch_size, "input_size": list(input_size) if input_size else None, "precision": precision, "extra_options": extra_options or {}})
        return {"task_id": t.task_id, "status": t.status, "queue_name": POSE_TRAINING_QUEUE_NAME, "queue_task_id": qid}

    def process(self, task_record: TaskRecord, *, model_type: str):
        meta = task_record.metadata or {}; p = meta.get("queue_payload", {})
        if not p:
            from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
            with SqlAlchemyUnitOfWork(self.sf) as uow:
                t = uow.tasks.get(task_record.task_id)
                if t: p = t.metadata or {}
        deid = p.get("dataset_export_id"); mk = p.get("dataset_export_manifest_key")
        if not deid or not mk: raise InvalidRequestError("pose 训练缺少 dataset_export_id")
        manifest = self.ds.read_json(mk)
        if not isinstance(manifest, dict): raise InvalidRequestError("pose 训练 manifest 无效")
        isz = None; ris = p.get("input_size")
        if isinstance(ris, list) and len(ris) == 2: isz = (int(ris[0]), int(ris[1]))
        op = f"task-runs/{task_record.task_id}"
        def on_sp(sv): self.ds.write_bytes(f"{op}/latest-checkpoint.pt", sv.latest_checkpoint_bytes)
        try:
            result = run_yolo_primary_pose_training(YoloPrimaryPoseTrainingExecutionRequest(dataset_storage=self.ds, manifest_payload=manifest, model_type=model_type, model_scale=str(p.get("model_scale", "n")), batch_size=int(p.get("batch_size") or 1), max_epochs=int(p.get("max_epochs") or 1), evaluation_interval=int(p.get("evaluation_interval") or 5), input_size=isz, precision=str(p.get("precision") or "fp32"), extra_options=p.get("extra_options", {}), savepoint_callback=on_sp))
        except YoloPrimaryPoseTrainingTerminatedError: return {"status": "terminated"}
        except YoloPrimaryPoseTrainingPausedError: return {"status": "paused"}
        self.ds.write_json(f"{op}/output-files/train-metrics.json", result.metrics_payload)
        self.ds.write_json(f"{op}/output-files/labels.json", {"labels": list(result.labels)})
        return {"status": "completed", "task_id": task_record.task_id}
