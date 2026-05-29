"""YOLO 主线非 detection 训练队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.models.yolo_primary_classification_training_service import (
    SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.yolo_primary_segmentation_training_service import (
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.yolo_primary_pose_training_service import (
    POSE_TRAINING_QUEUE_NAME,
    POSE_TRAINING_TASK_KIND,
    SqlAlchemyPoseTrainingTaskService,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class ClassificationTrainingQueueWorker:
    """消费 classification 训练队列。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage, queue_backend: QueueBackend, worker_id: str = "classification-training-worker") -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        qt = self.queue_backend.claim_next(YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME, self.worker_id)
        if qt is None:
            return False
        try:
            task_id = _read_task_id(qt)
            service = SqlAlchemyYoloPrimaryClassificationTrainingTaskService(session_factory=self.session_factory, queue_backend=self.queue_backend, dataset_storage=self.dataset_storage)
            task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
            task = task_service.get_task(task_id)
            service.process_training_task(task, model_type=_read_model_type(qt.payload))
        except Exception as exc:
            raise ServiceError(f"classification 训练执行失败: {exc}") from exc
        return True


class SegmentationTrainingQueueWorker:
    """消费 segmentation 训练队列。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage, queue_backend: QueueBackend, worker_id: str = "segmentation-training-worker") -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        qt = self.queue_backend.claim_next(YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME, self.worker_id)
        if qt is None:
            return False
        try:
            task_id = _read_task_id(qt)
            service = SqlAlchemyYoloPrimarySegmentationTrainingTaskService(session_factory=self.session_factory, queue_backend=self.queue_backend, dataset_storage=self.dataset_storage)
            task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
            task = task_service.get_task(task_id)
            service.process_training_task(task, model_type=_read_model_type(qt.payload))
        except Exception as exc:
            raise ServiceError(f"segmentation 训练执行失败: {exc}") from exc
        return True


class PoseTrainingQueueWorker:
    """消费 pose 训练队列。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage, queue_backend: QueueBackend, worker_id: str = "pose-training-worker") -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        qt = self.queue_backend.claim_next(POSE_TRAINING_QUEUE_NAME, self.worker_id)
        if qt is None:
            return False
        try:
            task_id = _read_task_id(qt)
            service = SqlAlchemyPoseTrainingTaskService(session_factory=self.session_factory, queue_backend=self.queue_backend, dataset_storage=self.dataset_storage)
            task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
            task = task_service.get_task(task_id)
            service.process(task, model_type=_read_model_type(qt.payload))
        except Exception as exc:
            raise ServiceError(f"pose 训练执行失败: {exc}") from exc
        return True


class ObbTrainingQueueWorker:
    """消费 obb 训练队列。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage, queue_backend: QueueBackend, worker_id: str = "obb-training-worker") -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        from backend.service.application.models.yolo_primary_obb_training import run_yolo_primary_obb_training, YoloPrimaryObbTrainingExecutionRequest
        qt = self.queue_backend.claim_next("obb-trainings", self.worker_id)
        if qt is None:
            return False
        try:
            task_id = _read_task_id(qt)
            task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
            task = task_service.get_task(task_id)
            payload = (task.metadata or {}).get("queue_payload", {})
            manifest_key = payload.get("dataset_export_manifest_key", "")
            if manifest_key:
                manifest = self.dataset_storage.read_json(manifest_key)
            else:
                manifest = {}
            run_yolo_primary_obb_training(YoloPrimaryObbTrainingExecutionRequest(
                dataset_storage=self.dataset_storage, manifest_payload=manifest,
                model_scale=payload.get("model_scale", "nano"), batch_size=int(payload.get("batch_size", 1)),
                max_epochs=int(payload.get("max_epochs", 1)),
                extra_options=payload.get("extra_options", {}),
            ))
        except Exception as exc:
            raise ServiceError(f"obb 训练执行失败: {exc}") from exc
        return True


def _read_task_id(qt: QueueMessage) -> str:
    import json
    payload = qt.payload
    if isinstance(payload, dict):
        return str(payload.get("task_id", ""))
    if isinstance(payload, str):
        return str(json.loads(payload).get("task_id", ""))
    raise InvalidRequestError("训练队列任务缺少 task_id")


def _read_model_type(payload: dict | str) -> str:
    import json
    if isinstance(payload, str):
        payload = json.loads(payload)
    model_type = str(payload.get("model_type", payload.get("model_scale", "yolov8")))
    if not model_type or model_type in ("s", "m", "l", "x", "nano"):
        return "yolov8"
    return model_type
