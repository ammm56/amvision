"""系统级 REST 路由。"""

from __future__ import annotations

from fastapi import APIRouter


system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.get("/health")
def get_service_health() -> dict[str, str]:
    """返回最小健康检查结果。

    返回：
    - 当前服务健康状态。
    """

    return {"status": "ok"}