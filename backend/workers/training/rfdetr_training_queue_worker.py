"""RF-DETR 训练队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.backends import TrainingBackend, TrainingBackendRunRequest
from backend.service.application.errors import InvalidRequestError, OperationCancelledError, ServiceError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.training.rfdetr_trainer_runner import SqlAlchemyRfdetrTrainerRunner


RFDETR_TRAINING_QUEUE_NAME = "rfdetr-trainings"
RFDETR_TRAINING_TASK_KIND = "rfdetr-training"


class RfdetrTrainingQueueWorker:
    """消费 RF-DETR 训练队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        training_backend: TrainingBackend | None = None,
        worker_id: str = "rfdetr-training-worker",
    ) -> None:
        """初始化 RF-DETR 训练队列 worker。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        - queue_backend：任务队列后端。
        - training_backend：可选训练执行器；测试场景可注入替代执行器。
        - worker_id：当前 worker 的稳定标识。
        """
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.training_backend = training_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 RF-DETR 训练队列任务。"""
        queue_task = self.queue_backend.claim_next(
            queue_name=RFDETR_TRAINING_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            task_id = self._read_task_id(queue_task)
            training_backend = self.training_backend or SqlAlchemyRfdetrTrainerRunner(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
            )
            run_result = training_backend.run_training(
                TrainingBackendRunRequest(
                    training_task_id=task_id,
                    model_type="rfdetr",
                    task_type=self._read_task_type(queue_task),
                    metadata={
                        "queue_task_id": queue_task.task_id,
                    },
                )
            )
        except OperationCancelledError as error:
            self.queue_backend.complete(
                queue_task,
                metadata={
                    "task_id": queue_task.payload.get("task_id"),
                    "status": "cancelled",
                    "cancel_message": error.message,
                },
            )
            return True
        except ServiceError as error:
            self.queue_backend.fail(
                queue_task,
                error_message=error.message,
                metadata={
                    "task_id": queue_task.payload.get("task_id"),
                },
            )
            return True
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata={
                    "task_id": queue_task.payload.get("task_id"),
                    "error_type": error.__class__.__name__,
                },
            )
            return True

        self.queue_backend.complete(
            queue_task,
            metadata={
                "task_id": run_result.training_task_id,
                "status": run_result.status,
                "dataset_export_id": run_result.dataset_export_id,
                "dataset_export_manifest_key": run_result.dataset_export_manifest_key,
                "dataset_version_id": run_result.dataset_version_id,
                "format_id": run_result.format_id,
                "output_object_prefix": run_result.output_object_prefix,
                "checkpoint_object_key": run_result.checkpoint_object_key,
                "latest_checkpoint_object_key": run_result.latest_checkpoint_object_key,
                "labels_object_key": run_result.labels_object_key,
                "metrics_object_key": run_result.metrics_object_key,
                "validation_metrics_object_key": run_result.validation_metrics_object_key,
                "summary_object_key": run_result.summary_object_key,
            },
        )
        return True

    def _read_task_id(self, queue_task: QueueMessage) -> str:
        """从队列负载中读取训练任务 id。"""
        import json

        payload = queue_task.payload
        if isinstance(payload, dict):
            task_id = payload.get("task_id")
        else:
            task_id = json.loads(payload).get("task_id")

        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "训练队列任务缺少 task_id",
                details={"queue_task_id": queue_task.task_id},
            )
        return task_id

    def _read_task_type(self, queue_task: QueueMessage) -> str:
        """从队列负载中读取 RF-DETR 训练 task_type。"""
        import json

        payload = queue_task.payload
        if isinstance(payload, dict):
            task_type = payload.get("task_type")
        else:
            task_type = json.loads(payload).get("task_type")

        if isinstance(task_type, str) and task_type.strip():
            return task_type.strip().lower()
        raise InvalidRequestError(
            "RF-DETR 训练队列负载缺少 task_type",
            details={"queue_task_id": queue_task.task_id},
        )
