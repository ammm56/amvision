"""YOLOX 评估队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.models.yolox_evaluation_task_service import (
    YOLOX_EVALUATION_QUEUE_NAME,
    SqlAlchemyYoloXEvaluationTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class YoloXEvaluationQueueWorker:
    """消费 yolox-evaluations 队列任务的最小 worker。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "yolox-evaluation-worker",
    ) -> None:
        """初始化 YOLOX 评估队列 worker。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 YOLOX 评估队列任务。"""

        queue_task = self.queue_backend.claim_next(
            queue_name=YOLOX_EVALUATION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            task_id = self._read_task_id(queue_task)
            service = SqlAlchemyYoloXEvaluationTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
            )
            run_result = service.process_evaluation_task(task_id)
        except ServiceError as error:
            self.queue_backend.fail(
                queue_task,
                error_message=error.message,
                metadata={
                    "task_id": queue_task.payload.get("task_id"),
                    "dataset_export_id": queue_task.metadata.get("dataset_export_id"),
                    "model_version_id": queue_task.metadata.get("model_version_id"),
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
                    "model_version_id": queue_task.metadata.get("model_version_id"),
                    "error_type": error.__class__.__name__,
                },
            )
            return True

        self.queue_backend.complete(
            queue_task,
            metadata={
                "task_id": run_result.task_id,
                "status": run_result.status,
                "dataset_export_id": run_result.dataset_export_id,
                "dataset_export_manifest_key": run_result.dataset_export_manifest_key,
                "dataset_version_id": run_result.dataset_version_id,
                "format_id": run_result.format_id,
                "model_version_id": run_result.model_version_id,
                "output_object_prefix": run_result.output_object_prefix,
                "report_object_key": run_result.report_object_key,
                "detections_object_key": run_result.detections_object_key,
                "result_package_object_key": run_result.result_package_object_key,
                "map50": run_result.map50,
                "map50_95": run_result.map50_95,
            },
        )
        return True

    def _read_task_id(self, queue_task: QueueMessage) -> str:
        """从队列负载中读取评估任务 id。"""

        task_id = queue_task.payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "评估队列任务缺少 task_id",
                details={"queue_task_id": queue_task.task_id},
            )
        return task_id