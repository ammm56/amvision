"""DatasetExport worker 接口与 SQLAlchemy 实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.service.application.datasets.dataset_export import (
    DatasetExportArtifact,
    SqlAlchemyDatasetExportTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class DatasetExportRunRequest:
    """描述一次 DatasetExport worker 执行请求。

    字段：
    - dataset_export_id：待处理的 DatasetExport 资源 id。
    - metadata：worker 侧附加元数据。
    """

    dataset_export_id: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetExportRunResult:
    """描述一次 DatasetExport worker 执行结果。

    字段：
    - task_id：处理的 TaskRecord id。
    - status：导出任务最终状态。
    - artifact：供 training 消费的 export file 边界。
    - metadata：worker 侧附加结果元数据。
    """

    task_id: str
    status: str
    artifact: DatasetExportArtifact
    metadata: dict[str, object] = field(default_factory=dict)


class DatasetExportRunner(Protocol):
    """执行 DatasetExport 处理任务的 worker 接口。"""

    def run_export(self, request: DatasetExportRunRequest) -> DatasetExportRunResult:
        """执行导出处理并返回结果。

        参数：
        - request：导出执行请求。

        返回：
        - 导出执行结果。
        """

        ...


class SqlAlchemyDatasetExportRunner:
    """基于 SQLAlchemy 与本地 ObjectStore 的 DatasetExport worker。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 DatasetExport worker。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def run_export(self, request: DatasetExportRunRequest) -> DatasetExportRunResult:
        """执行 DatasetExport 后处理链路。

        参数：
        - request：导出执行请求。

        返回：
        - 导出执行结果。
        """

        service = SqlAlchemyDatasetExportTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )
        task_result = service.process_export_task(request.dataset_export_id)
        return DatasetExportRunResult(
            task_id=task_result.task_id,
            status=task_result.status,
            artifact=task_result.artifact,
            metadata=dict(request.metadata),
        )