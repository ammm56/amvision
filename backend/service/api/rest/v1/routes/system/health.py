"""system health 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.service.api.rest.v1.routes.system.services import build_local_buffer_broker_health


system_health_router = APIRouter()


@system_health_router.get("/health")
def get_service_health(request: Request) -> dict[str, object]:
    """返回最小健康检查结果。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前服务健康状态。
    """

    return {
        "status": "ok",
        "request_id": request.state.request_id,
        "local_buffer_broker": build_local_buffer_broker_health(request),
    }

