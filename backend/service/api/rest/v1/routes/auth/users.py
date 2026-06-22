"""auth 本地用户管理路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.routes.auth.responses import (
    build_local_auth_user_contract,
    build_local_auth_user_create_contract,
)
from backend.service.api.rest.v1.routes.auth.schemas import (
    LocalAuthPasswordResetRequestBody,
    LocalAuthUserContract,
    LocalAuthUserCreateContract,
    LocalAuthUserCreateRequestBody,
    LocalAuthUserUpdateRequestBody,
)
from backend.service.api.rest.v1.routes.auth.services import (
    build_initial_user_token_create_request,
    build_local_auth_service,
)
from backend.service.application.auth.local_auth_service import (
    LocalAuthPasswordResetRequest,
    LocalAuthUserCreateRequest,
    LocalAuthUserUpdateRequest,
)


auth_users_router = APIRouter()


@auth_users_router.get(
    "/users",
    response_model=list[LocalAuthUserContract],
)
def list_local_auth_users(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:read"))],
) -> list[LocalAuthUserContract]:
    """列出当前全部本地用户。"""

    _ = principal
    return [build_local_auth_user_contract(item) for item in build_local_auth_service(request).list_users()]


@auth_users_router.post(
    "/users",
    response_model=LocalAuthUserCreateContract,
    status_code=status.HTTP_201_CREATED,
)
def create_local_auth_user(
    body: LocalAuthUserCreateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> LocalAuthUserCreateContract:
    """创建一个本地用户，并默认签发长期调用 token。"""

    user_create_result = build_local_auth_service(request).create_user(
        LocalAuthUserCreateRequest(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            principal_type=body.principal_type,
            project_ids=tuple(body.project_ids),
            scopes=tuple(body.scopes),
            metadata=dict(body.metadata),
            initial_user_token=build_initial_user_token_create_request(body.initial_user_token),
        ),
        created_by_user_id=principal.principal_id,
    )
    return build_local_auth_user_create_contract(user_create_result)


@auth_users_router.patch(
    "/users/{user_id}",
    response_model=LocalAuthUserContract,
)
def update_local_auth_user(
    user_id: str,
    body: LocalAuthUserUpdateRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> LocalAuthUserContract:
    """更新一个本地用户。"""

    _ = principal
    user = build_local_auth_service(request).update_user(
        user_id,
        LocalAuthUserUpdateRequest(
            display_name=body.display_name,
            password=body.password,
            project_ids=None if body.project_ids is None else tuple(body.project_ids),
            scopes=None if body.scopes is None else tuple(body.scopes),
            is_active=body.is_active,
            metadata=None if body.metadata is None else dict(body.metadata),
        ),
    )
    return build_local_auth_user_contract(user)


@auth_users_router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_local_auth_user(
    user_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> Response:
    """删除一个本地用户及其关联凭据。"""

    build_local_auth_service(request).delete_user(user_id, actor_user_id=principal.principal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_users_router.post(
    "/users/{user_id}/reset-password",
    response_model=LocalAuthUserContract,
)
def reset_local_auth_user_password(
    user_id: str,
    body: LocalAuthPasswordResetRequestBody,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("auth:write"))],
) -> LocalAuthUserContract:
    """重置一个本地用户密码，并按需撤销其现有凭据。"""

    _ = principal
    user = build_local_auth_service(request).reset_user_password(
        user_id,
        LocalAuthPasswordResetRequest(
            new_password=body.new_password,
            revoke_sessions=body.revoke_sessions,
            revoke_user_tokens=body.revoke_user_tokens,
        ),
        actor_user_id=principal.principal_id,
    )
    return build_local_auth_user_contract(user)

