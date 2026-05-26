"""FastAPI 应用装配入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.queue import LocalFileQueueBackend
from backend.service.api.bootstrap import BackendServiceBootstrap
from backend.service.api.seeders import BackendServiceSeeder
from backend.service.api.error_handlers import register_exception_handlers
from backend.service.api.middleware.request_context import RequestContextMiddleware
from backend.service.api.rest.router import rest_router
from backend.service.api.ws.router import ws_router
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings


def _register_cors_middleware(
    application: FastAPI,
    settings: BackendServiceSettings,
) -> None:
    """按统一配置注册 CORS 中间件。

    参数：
    - application：当前 FastAPI 应用。
    - settings：当前 backend-service 配置。
    """

    if not settings.cors.enabled:
        return
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors.allow_origins),
        allow_origin_regex=settings.cors.allow_origin_regex,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=list(settings.cors.allow_methods),
        allow_headers=list(settings.cors.allow_headers),
        expose_headers=list(settings.cors.expose_headers),
    )


def create_app(
    settings: BackendServiceSettings | None = None,
    session_factory: SessionFactory | None = None,
    dataset_storage: LocalDatasetStorage | None = None,
    queue_backend: LocalFileQueueBackend | None = None,
    seeders: tuple[BackendServiceSeeder, ...] | None = None,
) -> FastAPI:
    """创建 backend-service 的 FastAPI 应用。

    参数：
    - settings：可选的统一配置对象；未传入时按 config JSON 和环境变量读取。
    - session_factory：可选的数据库会话工厂；未传入时使用默认配置创建。
    - dataset_storage：可选的数据集本地文件存储服务；未传入时使用默认配置创建。
    - queue_backend：可选的本地任务队列后端；未传入时使用默认配置创建。
    - seeders：可选的启动期 seeder 列表。

    返回：
    - 已完成路由和基础中间件装配的 FastAPI 应用。
    """

    bootstrap = BackendServiceBootstrap(
        settings=settings,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        seeders=seeders,
    )
    resolved_settings = bootstrap.load_settings()
    runtime = bootstrap.build_runtime(resolved_settings)

    @asynccontextmanager
    async def application_lifespan(_application: FastAPI):
        """在应用生命周期启动阶段执行服务级初始化。"""

        bootstrap.initialize(runtime)
        bootstrap.start_runtime(runtime)
        try:
            yield
        finally:
            bootstrap.stop_runtime(runtime)

    application = FastAPI(
        title=resolved_settings.app.app_name,
        version=resolved_settings.app.app_version,
        lifespan=application_lifespan,
    )
    bootstrap.bind_application_state(application, runtime)

    _register_cors_middleware(application, resolved_settings)
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(rest_router)
    application.include_router(ws_router)

    return application


app = create_app()