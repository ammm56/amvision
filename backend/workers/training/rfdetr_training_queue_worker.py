"""RF-DETR 训练队列 worker。"""

from __future__ import annotations
from backend.queue import QueueBackend, QueueMessage
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

RFDETR_TRAINING_QUEUE_NAME = "rfdetr-trainings"
RFDETR_TRAINING_TASK_KIND = "rfdetr-training"


class RfdetrTrainingQueueWorker:
    """消费 RF-DETR 训练队列。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage, queue_backend: QueueBackend, worker_id: str = "rfdetr-training-worker") -> None:
        self.session_factory = session_factory; self.dataset_storage = dataset_storage; self.queue_backend = queue_backend; self.worker_id = worker_id

    def run_once(self) -> bool:
        qt = self.queue_backend.claim_next(RFDETR_TRAINING_QUEUE_NAME, self.worker_id)
        if qt is None:
            return False
        try:
            from backend.service.application.models.rfdetr_training import run_rfdetr_training, RfdetrTrainingExecutionRequest
            task_id = _read_task_id(qt)
            task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
            task = task_service.get_task(task_id)
            payload = (task.metadata or {}).get("queue_payload", {})
            mk = payload.get("dataset_export_manifest_key", "")
            manifest = self.dataset_storage.read_json(mk) if mk else {}
            run_rfdetr_training(RfdetrTrainingExecutionRequest(
                dataset_storage=self.dataset_storage, manifest_payload=manifest,
                model_scale=payload.get("model_scale", "nano"),
                batch_size=int(payload.get("batch_size", 2)),
                max_epochs=int(payload.get("max_epochs", 1)),
                extra_options=payload.get("extra_options", {}),
            ))
        except Exception as exc:
            raise ServiceError(f"RF-DETR 训练执行失败: {exc}") from exc
        return True


def _read_task_id(qt: QueueMessage) -> str:
    import json
    p = qt.payload
    if isinstance(p, dict): return str(p.get("task_id", ""))
    return str(json.loads(p).get("task_id", ""))
