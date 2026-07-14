"""RF-DETR 转换队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    SqlAlchemyRfdetrConversionTaskService,
)
from backend.service.application.tasks.task_service import (
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.conversion_queue_failures import (
    build_conversion_queue_failure_metadata,
)
from backend.workers.conversion.rfdetr_conversion_runner import LocalRfdetrConversionRunner


RFDETR_CONVERSION_QUEUE_NAME = "rfdetr-conversions"
RFDETR_CONVERSION_TASK_KIND = "rfdetr-conversion"


class RfdetrConversionQueueWorker:
    """消费 RF-DETR 转换队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        conversion_runner: LocalRfdetrConversionRunner | None = None,
        worker_id: str = "rfdetr-conversion-worker",
    ) -> None:
        """初始化 RF-DETR 转换队列 worker。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地文件存储服务。
        - queue_backend：队列后端。
        - conversion_runner：可选转换执行器。
        - worker_id：worker 标识。
        """
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.conversion_runner = conversion_runner
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 RF-DETR 转换队列任务。"""
        queue_task = self.queue_backend.claim_next(
            queue_name=RFDETR_CONVERSION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            task_id = self._read_task_id(queue_task)
            service = SqlAlchemyRfdetrConversionTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
                conversion_runner=self.conversion_runner,
            )
            task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
            task_service.get_task(task_id)
            result_payload = service.process_conversion_task(task_id)

        except ServiceError as error:
            self.queue_backend.fail(
                queue_task,
                error_message=error.message,
                metadata=build_conversion_queue_failure_metadata(queue_task, error),
            )
            return True
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata=build_conversion_queue_failure_metadata(queue_task, error),
            )
            return True

        self.queue_backend.complete(
            queue_task,
            metadata={
                "task_id": task_id,
                "status": "succeeded",
                "source_model_version_id": result_payload.get("source_model_version_id"),
                "output_object_prefix": result_payload.get("output_object_prefix"),
                "report_object_key": result_payload.get("report_object_key"),
                "produced_formats": result_payload.get("produced_formats"),
                "build_count": len(result_payload.get("builds") or []),
            },
        )
        return True

    @staticmethod
    def _read_task_id(queue_task: QueueMessage) -> str:
        """从队列负载中读取转换任务 id。"""
        import json

        payload = queue_task.payload
        if isinstance(payload, dict):
            task_id = payload.get("task_id")
        else:
            task_id = json.loads(payload).get("task_id")

        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "转换队列任务缺少 task_id",
                details={"queue_task_id": queue_task.task_id},
            )
        return task_id
