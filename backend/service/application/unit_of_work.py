"""应用层 Unit of Work 协议定义。"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.sql import Executable

from backend.service.domain.datasets.dataset_import_repository import DatasetImportRepository
from backend.service.domain.datasets.dataset_version_repository import DatasetVersionRepository
from backend.service.domain.files.model_file_repository import ModelFileRepository
from backend.service.domain.models.model_repository import ModelRepository
from backend.service.domain.tasks.resource_profile_repository import ResourceProfileRepository
from backend.service.domain.tasks.task_repository import TaskRepository


class UnitOfWork(Protocol):
    """描述请求级事务与聚合仓储边界。

    属性：
    - dataset_imports：DatasetImport 仓储。
    - datasets：DatasetVersion 聚合仓储。
    - models：Model 聚合仓储。
    - model_files：ModelFile 仓储。
    - tasks：TaskRecord、TaskAttempt、TaskEvent 仓储。
    - resource_profiles：ResourceProfile 仓储。
    """

    dataset_imports: DatasetImportRepository
    datasets: DatasetVersionRepository
    models: ModelRepository
    model_files: ModelFileRepository
    tasks: TaskRepository
    resource_profiles: ResourceProfileRepository

    def scalar(self, statement: Executable) -> object | None:
        """执行查询并返回标量结果。

        参数：
        - statement：要执行的 SQLAlchemy 语句。

        返回：
        - 查询得到的标量结果。
        """

        ...

    def commit(self) -> None:
        """提交当前事务。"""

        ...

    def rollback(self) -> None:
        """回滚当前事务。"""

        ...

    def close(self) -> None:
        """关闭当前事务持有的资源。"""

        ...