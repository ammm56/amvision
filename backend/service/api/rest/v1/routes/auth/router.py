"""auth REST 路由装配。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.routes.auth.bootstrap_admin import auth_bootstrap_admin_router
from backend.service.api.rest.v1.routes.auth.providers import auth_providers_router
from backend.service.api.rest.v1.routes.auth.sessions import auth_sessions_router
from backend.service.api.rest.v1.routes.auth.tokens import auth_tokens_router
from backend.service.api.rest.v1.routes.auth.users import auth_users_router


auth_router = APIRouter(prefix="/auth", tags=["auth"])
auth_router.include_router(auth_bootstrap_admin_router)
auth_router.include_router(auth_providers_router)
auth_router.include_router(auth_sessions_router)
auth_router.include_router(auth_users_router)
auth_router.include_router(auth_tokens_router)

