"""基于 SQLAlchemy 的 Unit of Work 实现。"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from backend.service.application.errors import PersistenceOperationError
from backend.service.infrastructure.persistence.dataset_export_repository import SqlAlchemyDatasetExportRepository
from backend.service.infrastructure.persistence.dataset_import_repository import SqlAlchemyDatasetImportRepository
from backend.service.infrastructure.persistence.model_file_repository import SqlAlchemyModelFileRepository
from backend.service.infrastructure.persistence.dataset_repository import SqlAlchemyDatasetVersionRepository
from backend.service.infrastructure.persistence.model_repository import SqlAlchemyModelRepository
from backend.service.infrastructure.persistence.resource_profile_repository import (
    SqlAlchemyResourceProfileRepository,
)
from backend.service.infrastructure.persistence.task_repository import SqlAlchemyTaskRepository


class SqlAlchemyUnitOfWork:
    """封装请求级数据库事务和基础执行能力。

    属性：
    - session：当前 Unit of Work 持有的 SQLAlchemy Session。
    - dataset_exports：DatasetExport 仓储。
    - dataset_imports：DatasetImport 仓储。
    - datasets：DatasetVersion 聚合仓储。
    - models：Model 聚合仓储。
    - model_files：ModelFile 仓储。
    - tasks：TaskRecord、TaskAttempt、TaskEvent 仓储。
    - resource_profiles：ResourceProfile 仓储。
    """

    def __init__(self, session: Session) -> None:
        """初始化 Unit of Work。

        参数：
        - session：当前要管理的 SQLAlchemy Session。
        """

        self.session = session
        self.dataset_exports = SqlAlchemyDatasetExportRepository(session)
        self.dataset_imports = SqlAlchemyDatasetImportRepository(session)
        self.datasets = SqlAlchemyDatasetVersionRepository(session)
        self.models = SqlAlchemyModelRepository(session)
        self.model_files = SqlAlchemyModelFileRepository(session)
        self.tasks = SqlAlchemyTaskRepository(session)
        self.resource_profiles = SqlAlchemyResourceProfileRepository(session)

    def scalar(self, statement: Executable) -> object | None:
        """执行查询并返回第一列的标量结果。

        参数：
        - statement：要执行的 SQLAlchemy 语句。

        返回：
        - 查询得到的标量结果；不存在时返回 None。

        异常：
        - 当数据库执行失败时抛出持久化错误。
        """

        try:
            return self.session.execute(statement).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "数据库查询失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def commit(self) -> None:
        """提交当前事务。

        异常：
        - 当数据库提交失败时抛出持久化错误。
        """

        try:
            self.session.commit()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "数据库提交失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def rollback(self) -> None:
        """回滚当前事务。"""

        try:
            self.session.rollback()
        except SQLAlchemyError:
            # rollback 失败时优先保持原始异常冒泡，不额外覆盖。
            return

    def close(self) -> None:
        """关闭当前 Session。"""

        self.session.close()