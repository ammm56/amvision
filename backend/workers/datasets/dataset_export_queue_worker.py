"""DatasetExport 队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.datasets.dataset_export import DATASET_EXPORT_QUEUE_NAME
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.datasets.dataset_export_runner import (
    DatasetExportRunRequest,
    SqlAlchemyDatasetExportRunner,
)


class DatasetExportQueueWorker:
    """消费 DatasetExport 队列任务的最小 worker。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "dataset-export-worker",
    ) -> None:
        """初始化 DatasetExport 队列 worker。

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
        """消费并执行一条 DatasetExport 队列任务。

        返回：
        - 当成功领取并处理了一条任务时返回 True；没有可处理任务时返回 False。
        """

        queue_task = self.queue_backend.claim_next(
            queue_name=DATASET_EXPORT_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            dataset_export_id = self._read_dataset_export_id(queue_task)
            runner = SqlAlchemyDatasetExportRunner(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
            )
            run_result = runner.run_export(
                DatasetExportRunRequest(dataset_export_id=dataset_export_id)
            )
        except ServiceError as error:
            self.queue_backend.fail(
                queue_task,
                error_message=error.message,
                metadata={
                    "dataset_export_id": queue_task.payload.get("dataset_export_id"),
                },
            )
            return True
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata={
                    "dataset_export_id": queue_task.payload.get("dataset_export_id"),
                    "error_type": error.__class__.__name__,
                },
            )
            return True

        self.queue_backend.complete(
            queue_task,
            metadata={
                "dataset_export_id": dataset_export_id,
                "task_id": run_result.task_id,
                "status": run_result.status,
                "dataset_version_id": run_result.artifact.dataset_version_id,
                "format_id": run_result.artifact.format_id,
                "manifest_object_key": run_result.artifact.manifest_object_key,
                "export_path": run_result.artifact.export_path,
            },
        )
        return True

    def _read_dataset_export_id(self, queue_task: QueueMessage) -> str:
        """从队列负载中读取 DatasetExport 资源 id。

        参数：
        - queue_task：当前领取到的队列任务。

        返回：
        - 要执行的 DatasetExport 资源 id。

        异常：
        - 当负载缺少 dataset_export_id 时抛出请求错误。
        """

        dataset_export_id = queue_task.payload.get("dataset_export_id")
        if not isinstance(dataset_export_id, str) or not dataset_export_id.strip():
            raise InvalidRequestError(
                "导出队列任务缺少 dataset_export_id",
                details={"task_id": queue_task.task_id},
            )

        return dataset_export_id