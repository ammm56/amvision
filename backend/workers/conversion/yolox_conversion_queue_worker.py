"""YOLOX 转换队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.backends import ConversionBackend
from backend.service.application.conversions.yolox_conversion_task_service import (
    YOLOX_CONVERSION_QUEUE_NAME,
    SqlAlchemyYoloXConversionTaskService,
)
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.conversion_queue_failures import (
    build_conversion_queue_failure_metadata,
)
from backend.workers.conversion.yolox_conversion_runner import (
    LocalYoloXConversionRunner,
)


class YoloXConversionQueueWorker:
    """消费 yolox-conversions 队列任务的最小 worker。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        conversion_runner: ConversionBackend | None = None,
        worker_id: str = "yolox-conversion-worker",
    ) -> None:
        """初始化 YOLOX 转换队列 worker。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.conversion_runner = conversion_runner
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 YOLOX 转换队列任务。"""

        queue_task = self.queue_backend.claim_next(
            queue_name=YOLOX_CONVERSION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            task_id = self._read_task_id(queue_task)
            service = SqlAlchemyYoloXConversionTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                conversion_runner=self.conversion_runner
                or LocalYoloXConversionRunner(dataset_storage=self.dataset_storage),
            )
            run_result = service.process_conversion_task(task_id)
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
                "task_id": run_result.task_id,
                "status": run_result.status,
                "source_model_version_id": run_result.source_model_version_id,
                "output_object_prefix": run_result.output_object_prefix,
                "plan_object_key": run_result.plan_object_key,
                "report_object_key": run_result.report_object_key,
                "produced_formats": list(run_result.produced_formats),
                "build_count": len(run_result.builds),
            },
        )
        return True

    @staticmethod
    def _read_task_id(queue_task: QueueMessage) -> str:
        """从队列负载中读取转换任务 id。"""

        task_id = queue_task.payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "转换队列任务缺少 task_id",
                details={"queue_task_id": queue_task.task_id},
            )
        return task_id

