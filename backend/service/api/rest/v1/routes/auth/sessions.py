"""auth 登录会话路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    get_request_bearer_token,
    require_principal,
)
from backend.service.api.rest.v1.routes.auth.responses import build_local_auth_session_contract
from backend.service.api.rest.v1.routes.auth.schemas import (
    LocalAuthLoginRequestBody,
    LocalAuthRefreshRequestBody,
    LocalAuthSessionContract,
)
from backend.service.api.rest.v1.routes.auth.services import (
    build_auth_provider_registry,
    build_local_auth_service,
)
from backend.service.application.errors import AuthenticationRequiredError, InvalidRequestError


auth_sessions_router = APIRouter()


@auth_sessions_router.post(
    "/login",
    response_model=LocalAuthSessionContract,
)
def login_local_auth_user(
    body: LocalAuthLoginRequestBody,
    request: Request,
) -> LocalAuthSessionContract:
    """按本地用户名和密码登录，并签发登录会话与 refresh token。"""

    session_result = build_auth_provider_registry(request).resolve_password_provider(body.provider_id).login(
        username=body.username,
        password=body.password,
    )
    return build_local_auth_session_contract(session_result)


@auth_sessions_router.post(
    "/refresh",
    response_model=LocalAuthSessionContract,
)
def refresh_local_auth_session(
    body: LocalAuthRefreshRequestBody,
    request: Request,
) -> LocalAuthSessionContract:
    """使用 refresh token 刷新登录会话。"""

    session_result = build_auth_provider_registry(request).resolve_password_provider("local").refresh_session(
        body.refresh_token
    )
    return build_local_auth_session_contract(session_result)


@auth_sessions_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout_local_auth_user(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> Response:
    """撤销当前请求携带的本地登录会话 access token。"""

    if principal.metadata.get("auth_credential_kind") != "session":
        raise InvalidRequestError("当前 Bearer token 不是登录会话，不能执行 logout")
    access_token = get_request_bearer_token(request)
    if access_token is None:
        raise AuthenticationRequiredError("当前请求未携带 Bearer token")
    revoked = build_local_auth_service(request).revoke_session_access_token(
        access_token,
        expected_user_id=principal.principal_id,
        actor_user_id=principal.principal_id,
    )
    if not revoked:
        raise InvalidRequestError("当前 access token 不支持本地注销")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

