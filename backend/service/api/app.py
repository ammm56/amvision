"""FastAPI 应用装配入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

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


class FrontendStaticFiles(StaticFiles):
    """为单页应用提供静态资源与路由回退。"""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        """优先返回静态文件；未命中时对无扩展名路径回退到 index.html。"""

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise

            request_path = Path(path)
            if request_path.name and "." in request_path.name:
                raise
            return await super().get_response("index.html", scope)


def _resolve_frontend_static_dir() -> Path | None:
    """按当前工作目录解析可供 backend-service 托管的前端静态目录。"""

    current_working_dir = Path.cwd().resolve()
    for candidate_dir in (
        current_working_dir / "frontend",
        current_working_dir / "frontend" / "web-ui" / "dist",
    ):
        if (candidate_dir / "index.html").is_file():
            return candidate_dir
    return None


def _register_frontend_static_files(application: FastAPI) -> None:
    """在当前目录存在前端构建产物时挂载浏览器端静态资源。"""

    frontend_static_dir = _resolve_frontend_static_dir()
    if frontend_static_dir is None:
        return
    application.mount(
        "/",
        FrontendStaticFiles(directory=str(frontend_static_dir), html=True),
        name="frontend",
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
    _register_frontend_static_files(application)

    return application


app = create_app()
