"""YOLOX 训练队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.models.yolox_training_service import YOLOX_TRAINING_QUEUE_NAME
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.training.yolox_trainer_runner import (
    SqlAlchemyYoloXTrainerRunner,
    YoloXTrainingRunRequest,
)


class YoloXTrainingQueueWorker:
    """消费 yolox-trainings 队列任务的最小 worker。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "yolox-training-worker",
    ) -> None:
        """初始化 YOLOX 训练队列 worker。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        - queue_backend：任务队列后端。
        - worker_id：当前 worker 的稳定标识。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 YOLOX 训练队列任务。

        返回：
        - 当成功领取并处理了一条任务时返回 True；没有可处理任务时返回 False。
        """

        queue_task = self.queue_backend.claim_next(
            queue_name=YOLOX_TRAINING_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            task_id = self._read_task_id(queue_task)
            runner = SqlAlchemyYoloXTrainerRunner(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
            )
            run_result = runner.run_training(
                YoloXTrainingRunRequest(
                    training_task_id=task_id,
                    metadata={
                        "queue_task_id": queue_task.task_id,
                    },
                )
            )
        except ServiceError as error:
            self.queue_backend.fail(
                queue_task,
                error_message=error.message,
                metadata={
                    "task_id": queue_task.payload.get("task_id"),
                    "dataset_export_id": queue_task.metadata.get("dataset_export_id"),
                },
            )
            return True
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata={
                    "task_id": queue_task.payload.get("task_id"),
                    "dataset_export_id": queue_task.metadata.get("dataset_export_id"),
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
        """从队列负载中读取训练任务 id。

        参数：
        - queue_task：当前领取到的队列任务。

        返回：
        - 要执行的训练任务 id。

        异常：
        - 当负载缺少 task_id 时抛出请求错误。
        """

        task_id = queue_task.payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "训练队列任务缺少 task_id",
                details={"queue_task_id": queue_task.task_id},
            )

        return task_id