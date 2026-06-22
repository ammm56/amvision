"""auth 长期调用 user token 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.routes.auth.responses import (
    build_local_auth_issued_user_token_contract,
    build_local_auth_user_token_contract,
)
from backend.service.api.rest.v1.routes.auth.schemas import (
    LocalAuthIssuedUserTokenContract,
    LocalAuthUserTokenContract,
    LocalAuthUserTokenCreateRequestBody,
)
from backend.service.api.rest.v1.routes.auth.services import build_local_auth_service
from backend.service.application.auth.local_auth_service import LocalAuthUserTokenCreateRequest
from backend.service.application.errors import ResourceNotFoundError


auth_tokens_router = APIRouter()


@auth_tokens_router.get(
    "/users/{user_id}/tokens",
    response_model=list[LocalAuthUserTokenContract],
)
def list_local_auth_user_tokens(
    user_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:read"))],
) -> list[LocalAuthUserTokenContract]:
    """列出一个本地用户的长期调用 token。"""

    _ = principal
    return [
        build_local_auth_user_token_contract(item)
        for item in build_local_auth_service(request).list_user_tokens(user_id)
    ]


@auth_tokens_router.post(
    "/users/{user_id}/tokens",
    response_model=LocalAuthIssuedUserTokenContract,
    status_code=status.HTTP_201_CREATED,
)
def create_local_auth_user_token(
    user_id: str,
    body: LocalAuthUserTokenCreateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> LocalAuthIssuedUserTokenContract:
    """为一个本地用户创建长期调用 token。"""

    issued_token = build_local_auth_service(request).create_user_token(
        user_id,
        LocalAuthUserTokenCreateRequest(
            token_name=body.token_name,
            ttl_hours=body.ttl_hours,
            expires_at=body.expires_at,
            metadata=dict(body.metadata),
        ),
        created_by_user_id=principal.principal_id,
    )
    return build_local_auth_issued_user_token_contract(issued_token)


@auth_tokens_router.delete(
    "/users/{user_id}/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_local_auth_user_token(
    user_id: str,
    token_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> Response:
    """撤销一个本地用户的长期调用 token。"""

    _ = principal
    revoked = build_local_auth_service(request).revoke_user_token(
        user_id,
        token_id,
        actor_user_id=principal.principal_id,
    )
    if not revoked:
        raise ResourceNotFoundError(
            "请求的本地 user token 不存在",
            details={"user_id": user_id, "token_id": token_id},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

