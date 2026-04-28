"""FastAPI 应用装配入口。"""

from __future__ import annotations

from fastapi import FastAPI

from backend.service.api.middleware.request_context import RequestContextMiddleware
from backend.service.api.rest.router import rest_router
from backend.service.api.ws.router import ws_router


def create_app() -> FastAPI:
    """创建 backend-service 的 FastAPI 应用。

    返回：
    - 已完成路由和基础中间件装配的 FastAPI 应用。
    """

    application = FastAPI(
        title="amvision backend-service",
        version="0.1.0",
    )
    application.add_middleware(RequestContextMiddleware)
    application.include_router(rest_router)
    application.include_router(ws_router)

    return application


app = create_app()