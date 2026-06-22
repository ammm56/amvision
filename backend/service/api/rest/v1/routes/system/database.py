"""system database 健康检查路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_unit_of_work
from backend.service.application.unit_of_work import UnitOfWork


system_database_router = APIRouter()


@system_database_router.get("/database")
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

