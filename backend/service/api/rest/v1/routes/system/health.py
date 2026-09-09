"""system health 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Literal

from backend.service.api.rest.v1.routes.system.services import build_local_buffer_broker_health


system_health_router = APIRouter()


class ServiceLivenessResponse(BaseModel):
    """HTTP 接入身份；不表示模型或其他业务依赖已经可用。"""

    format_id: Literal["amvision.service-liveness.v1"]
    instance_id: str = Field(pattern="^[0-9a-f]{32}$")
    pid: int = Field(gt=0)
    phase: Literal["starting", "ready", "draining", "stopped"]


@system_health_router.get("/liveness", response_model=ServiceLivenessResponse)
async def get_service_liveness(request: Request) -> dict[str, str | int]:
    """只读取当前进程内状态，验证新 HTTP 连接和事件循环可用。"""
    return request.app.state.service_liveness.snapshot()


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

