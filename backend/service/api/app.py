"""FastAPI 应用装配入口。"""

from __future__ import annotations

from fastapi import FastAPI

from backend.service.api.error_handlers import register_exception_handlers
from backend.service.api.middleware.request_context import RequestContextMiddleware
from backend.service.api.rest.router import rest_router
from backend.service.api.ws.router import ws_router
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def create_app(
    session_factory: SessionFactory | None = None,
    dataset_storage: LocalDatasetStorage | None = None,
) -> FastAPI:
    """创建 backend-service 的 FastAPI 应用。

    参数：
    - session_factory：可选的数据库会话工厂；未传入时使用默认配置创建。
    - dataset_storage：可选的数据集本地文件存储服务；未传入时使用默认配置创建。

    返回：
    - 已完成路由和基础中间件装配的 FastAPI 应用。
    """

    application = FastAPI(
        title="amvision backend-service",
        version="0.1.0",
    )
    application.state.session_factory = session_factory or SessionFactory(DatabaseSettings())
    application.state.dataset_storage = dataset_storage or LocalDatasetStorage(DatasetStorageSettings())
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(rest_router)
    application.include_router(ws_router)

    return application


app = create_app()