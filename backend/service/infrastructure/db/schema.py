"""数据库 schema 初始化辅助。"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.persistence.base import Base


def initialize_database_schema(session_factory: SessionFactory) -> None:
    """导入当前 ORM 实体并创建缺失的数据表。

    参数：
    - session_factory：当前服务使用的数据库会话工厂。

    异常：
    - 当数据库不可用或 schema 初始化失败时抛出服务配置错误。
    """

    _import_orm_models()
    try:
        Base.metadata.create_all(session_factory.engine)
    except SQLAlchemyError as error:
        raise ServiceConfigurationError(
            "数据库 schema 初始化失败",
            details={"error_type": error.__class__.__name__},
        ) from error


def _import_orm_models() -> None:
    """导入所有当前已注册的 ORM 模块。"""

    from backend.service.infrastructure.persistence import (  # noqa: PLC0415
        dataset_export_orm,
        dataset_import_orm,
        dataset_orm,
        deployment_orm,
        model_file_orm,
        model_orm,
        task_orm,
        workflow_runtime_orm,
    )

    _ = (
        dataset_export_orm,
        dataset_import_orm,
        dataset_orm,
        deployment_orm,
        model_file_orm,
        model_orm,
        task_orm,
        workflow_runtime_orm,
    )