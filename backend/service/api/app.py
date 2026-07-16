"""FastAPI 应用装配入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse

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

        runtime_config_response = self._resolve_runtime_config_response(path)
        if runtime_config_response is not None:
            return runtime_config_response

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise

            request_path = Path(path)
            if request_path.name and "." in request_path.name:
                raise
            return await super().get_response("index.html", scope)

    def _resolve_runtime_config_response(self, path: str) -> FileResponse | None:
        """为开发态静态托管补齐 runtime-config.json。

        前端构建产物可能只包含 `runtime-config.template.json`。直接由 backend-service
        托管 `frontend/web-ui/dist` 时，如果 `/runtime-config.json` 返回 404，旧构建包
        会继续使用编译期默认地址，容易在后端端口调整后出现离线页。这里仅对
        `runtime-config.json` 做受控 fallback，不影响其它静态文件和生产运行链路。
        """

        if path.replace("\\", "/") != "runtime-config.json":
            return None
        for static_dir in self.all_directories:
            static_path = Path(static_dir)
            for config_file_name in (
                "runtime-config.json",
                "runtime-config.local.json",
                "runtime-config.template.json",
            ):
                config_path = static_path / config_file_name
                if config_path.is_file():
                    return FileResponse(config_path, media_type="application/json")
        return None


_FRONTEND_STATIC_MIME_TYPES: dict[str, str] = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".map": "application/json",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}


def _register_frontend_static_mime_types() -> None:
    """固定前端构建产物的 MIME 类型，避免受 Windows 注册表污染影响。

    Windows 目标机可能把 `.js` 注册成 `text/plain`，Firefox / Chromium 会拒绝加载
    Vite 生成的 module script，导致发布包启动成功但前端空白。这里在服务挂载前显式
    覆盖常见前端资源类型，让 standalone/workstation 发布不依赖系统 MIME 表。
    """

    for suffix, media_type in _FRONTEND_STATIC_MIME_TYPES.items():
        mimetypes.add_type(media_type, suffix, strict=True)
        mimetypes.add_type(media_type, suffix, strict=False)


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
    _register_frontend_static_mime_types()
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
