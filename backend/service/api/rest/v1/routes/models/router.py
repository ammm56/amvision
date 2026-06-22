"""模型 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.rest.v1.routes.models.schemas import (
    PlatformBaseModelDetailResponse,
    PlatformBaseModelSummaryResponse,
)
from backend.service.api.rest.v1.routes.models.services import (
    get_platform_base_model_detail_response,
    list_platform_base_model_responses,
)
from backend.service.infrastructure.db.session import SessionFactory


models_router = APIRouter(prefix="/models", tags=["models"])


@models_router.get(
    "/platform-base",
    response_model=list[PlatformBaseModelSummaryResponse],
)
def list_platform_base_models(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    model_name: Annotated[str | None, Query(description="模型名筛选")] = None,
    model_scale: Annotated[str | None, Query(description="模型 scale 筛选")] = None,
    task_type: Annotated[str | None, Query(description="任务类型筛选")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
) -> list[PlatformBaseModelSummaryResponse]:
    """列出当前可见的平台基础模型。"""

    _ = principal
    return list_platform_base_model_responses(
        session_factory=session_factory,
        model_name=model_name,
        model_scale=model_scale,
        task_type=task_type,
        limit=limit,
    )


@models_router.get(
    "/platform-base/{model_id}",
    response_model=PlatformBaseModelDetailResponse,
)
def get_platform_base_model_detail(
    model_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> PlatformBaseModelDetailResponse:
    """按 id 返回单个平台基础模型详情。"""

    _ = principal
    return get_platform_base_model_detail_response(
        session_factory=session_factory,
        model_id=model_id,
    )
