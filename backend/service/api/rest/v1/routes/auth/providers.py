"""auth provider 发现路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.service.api.rest.v1.routes.auth.responses import build_auth_provider_contract
from backend.service.api.rest.v1.routes.auth.schemas import AuthProviderContract
from backend.service.api.rest.v1.routes.auth.services import build_auth_provider_registry


auth_providers_router = APIRouter()


@auth_providers_router.get(
    "/providers",
    response_model=list[AuthProviderContract],
)
def list_auth_providers(request: Request) -> list[AuthProviderContract]:
    """列出当前公开可发现的账号 provider。"""

    provider_registry = build_auth_provider_registry(request)
    return [build_auth_provider_contract(item) for item in provider_registry.list_providers()]

