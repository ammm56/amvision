"""auth bootstrap admin 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from backend.service.api.rest.v1.routes.auth.responses import build_local_auth_session_contract
from backend.service.api.rest.v1.routes.auth.schemas import (
    LocalAuthBootstrapAdminRequestBody,
    LocalAuthSessionContract,
)
from backend.service.api.rest.v1.routes.auth.services import build_local_auth_service
from backend.service.application.auth.local_auth_service import LocalAuthBootstrapAdminRequest


auth_bootstrap_admin_router = APIRouter()


@auth_bootstrap_admin_router.post(
    "/bootstrap-admin",
    response_model=LocalAuthSessionContract,
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_local_auth_admin(
    body: LocalAuthBootstrapAdminRequestBody,
    request: Request,
) -> LocalAuthSessionContract:
    """在本地用户表为空时初始化首个管理员账号。"""

    session_result = build_local_auth_service(request).bootstrap_admin(
        LocalAuthBootstrapAdminRequest(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
        )
    )
    return build_local_auth_session_contract(session_result)

