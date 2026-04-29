"""系统级 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from backend.service.application.unit_of_work import UnitOfWork
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_principal, require_scopes
from backend.service.api.deps.db import get_unit_of_work


system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.get("/health")
def get_service_health(request: Request) -> dict[str, str]:
    """返回最小健康检查结果。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前服务健康状态。
    """

    return {"status": "ok", "request_id": request.state.request_id}


@system_router.get("/me")
def get_current_principal(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> dict[str, object]:
    """返回当前请求主体信息。

    参数：
    - principal：已通过鉴权的调用主体。

    返回：
    - 当前主体的最小可见信息。
    """

    return {
        "principal_id": principal.principal_id,
        "principal_type": principal.principal_type,
        "project_ids": principal.project_ids,
        "scopes": principal.scopes,
    }


@system_router.get("/database")
def get_database_health(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("system:read"))],
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> dict[str, object]:
    """返回数据库连通性检查结果。

    参数：
    - request：当前 HTTP 请求。
    - principal：具备 system:read scope 的调用主体。
    - unit_of_work：当前请求级 Unit of Work。

    返回：
    - 数据库连通性检查结果。
    """

    health_value = unit_of_work.scalar(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "reachable",
        "scalar": health_value,
        "principal_id": principal.principal_id,
        "request_id": request.state.request_id,
    }