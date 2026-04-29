"""DatasetImport worker 接口与 SQLAlchemy 实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.service.application.datasets.dataset_import import (
    DatasetImportResult,
    SqlAlchemyDatasetImportService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class DatasetImportRunRequest:
    """描述一次 DatasetImport worker 执行请求。

    字段：
    - dataset_import_id：待处理的 DatasetImport id。
    - metadata：worker 侧附加元数据。
    """

    dataset_import_id: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetImportRunResult:
    """描述一次 DatasetImport worker 执行结果。

    字段：
    - dataset_import_id：处理的 DatasetImport id。
    - dataset_version_id：生成的 DatasetVersion id。
    - status：导入完成后的状态。
    - sample_count：样本总数。
    - category_count：类别总数。
    - split_names：最终包含的 split 列表。
    - metadata：worker 侧附加结果元数据。
    """

    dataset_import_id: str
    dataset_version_id: str | None
    status: str
    sample_count: int
    category_count: int
    split_names: tuple[str, ...]
    metadata: dict[str, object] = field(default_factory=dict)


class DatasetImportRunner(Protocol):
    """执行 DatasetImport 处理任务的 worker 接口。"""

    def run_import(self, request: DatasetImportRunRequest) -> DatasetImportRunResult:
        """执行导入处理并返回结果。

        参数：
        - request：导入执行请求。

        返回：
        - 导入执行结果。
        """

        ...


class SqlAlchemyDatasetImportRunner:
    """基于 SQLAlchemy 与本地 ObjectStore 的 DatasetImport worker。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 DatasetImport worker。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def run_import(self, request: DatasetImportRunRequest) -> DatasetImportRunResult:
        """执行 DatasetImport 后处理链路。

        参数：
        - request：导入执行请求。

        返回：
        - 导入执行结果。
        """

        service = SqlAlchemyDatasetImportService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )
        import_result = service.process_dataset_import(request.dataset_import_id)
        return self._build_run_result(import_result=import_result, request=request)

    def _build_run_result(
        self,
        *,
        import_result: DatasetImportResult,
        request: DatasetImportRunRequest,
    ) -> DatasetImportRunResult:
        """把应用层结果转换为 worker 输出对象。

        参数：
        - import_result：应用层导入结果。
        - request：导入执行请求。

        返回：
        - worker 输出结果。
        """

        dataset_import = import_result.dataset_import
        return DatasetImportRunResult(
            dataset_import_id=dataset_import.dataset_import_id,
            dataset_version_id=dataset_import.dataset_version_id,
            status=dataset_import.status,
            sample_count=import_result.sample_count,
            category_count=import_result.category_count,
            split_names=import_result.split_names,
            metadata=dict(request.metadata),
        )