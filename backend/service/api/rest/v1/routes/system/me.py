"""system 当前主体路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_principal
from backend.service.api.rest.v1.routes.system.responses import build_current_principal_contract


system_me_router = APIRouter()


@system_me_router.get("/me")
def get_current_principal(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> dict[str, object]:
    """返回当前请求主体信息。

    参数：
    - request：当前 HTTP 请求。
    - principal：已通过鉴权的调用主体。

    返回：
    - 当前主体的最小可见信息。
    """

    payload = build_current_principal_contract(principal).model_dump(mode="json")
    payload["auth_mode"] = getattr(request.app.state.backend_service_settings.auth, "mode", None)
    return payload

