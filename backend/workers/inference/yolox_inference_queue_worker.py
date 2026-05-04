"""YOLOX 推理队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.models.yolox_inference_task_service import (
    YOLOX_INFERENCE_QUEUE_NAME,
    SqlAlchemyYoloXInferenceTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class YoloXInferenceQueueWorker:
    """消费 yolox-inferences 队列任务的最小 worker。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "yolox-inference-worker",
    ) -> None:
        """初始化 YOLOX 推理队列 worker。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 YOLOX 推理队列任务。"""

        queue_task = self.queue_backend.claim_next(
            queue_name=YOLOX_INFERENCE_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            task_id = self._read_task_id(queue_task)
            service = SqlAlchemyYoloXInferenceTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
            )
            run_result = service.process_inference_task(task_id)
        except ServiceError as error:
            self.queue_backend.fail(
                queue_task,
                error_message=error.message,
                metadata={"task_id": queue_task.payload.get("task_id")},
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
                "task_id": run_result.task_id,
                "status": run_result.status,
                "deployment_instance_id": run_result.deployment_instance_id,
                "model_version_id": run_result.model_version_id,
                "model_build_id": run_result.model_build_id,
                "output_object_prefix": run_result.output_object_prefix,
                "result_object_key": run_result.result_object_key,
                "preview_image_object_key": run_result.preview_image_object_key,
                "detection_count": run_result.detection_count,
                "latency_ms": run_result.latency_ms,
            },
        )
        return True

    @staticmethod
    def _read_task_id(queue_task: QueueMessage) -> str:
        """从队列负载中读取推理任务 id。"""

        task_id = queue_task.payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "推理队列任务缺少 task_id",
                details={"queue_task_id": queue_task.task_id},
            )
        return task_id