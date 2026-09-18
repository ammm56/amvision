"""高频视觉服务状态查询；默认请求仅返回已序列化的内存摘要。"""

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.service.api.deps.auth import resolve_request_principal
from backend.service.application.errors import (
    AuthenticationRequiredError,
    PermissionDeniedError,
)

system_status_router = APIRouter()


class ServiceStatusCount(BaseModel):
    """要求运行的资源数与已就绪资源数，不是空闲容量。"""

    expected: int
    ready: int


class ServiceStatusBlocker(BaseModel):
    """稳定的组件类别和未就绪原因码。"""

    kind: str
    code: str


class ServiceStatusResponse(BaseModel):
    """服务整体状态；满载、推理中和长任务均可为 ready。"""

    ready: bool
    state: Literal["starting", "ready", "degraded", "unavailable", "stopping"]
    instance_id: str
    checked_at: str | None
    summary: dict[str, ServiceStatusCount] | None
    blockers: list[ServiceStatusBlocker]
    resources: list[dict[str, object]] | None = None


@system_status_router.get(
    "/status",
    response_model=ServiceStatusResponse,
    responses={503: {"model": ServiceStatusResponse}},
)
async def get_service_status(request: Request, details: bool = False) -> Response:
    """返回全局摘要；仅管理员可按需读取含资源 id 的完整明细。"""
    if details:
        # 明细沿用现有鉴权，普通高频摘要完全不访问数据库。
        principal = await run_in_threadpool(resolve_request_principal, request)
        if principal is None:
            raise AuthenticationRequiredError()
        if "*" not in principal.scopes:
            raise PermissionDeniedError("服务全局状态明细仅允许管理员读取")
    monitor = request.app.state.service_status_monitor
    code, body = monitor.response(
        details=details,
        stopping=request.app.state.service_liveness.phase in {"draining", "stopped"},
    )
    return Response(
        body,
        status_code=code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
