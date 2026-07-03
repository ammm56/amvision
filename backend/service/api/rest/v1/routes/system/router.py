"""system REST 路由装配。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.routes.system.bootstrap import system_bootstrap_router
from backend.service.api.rest.v1.routes.system.config import system_config_router
from backend.service.api.rest.v1.routes.system.database import system_database_router
from backend.service.api.rest.v1.routes.system.diagnostics import system_diagnostics_router
from backend.service.api.rest.v1.routes.system.health import system_health_router
from backend.service.api.rest.v1.routes.system.me import system_me_router


system_router = APIRouter(prefix="/system", tags=["system"])
system_router.include_router(system_health_router)
system_router.include_router(system_bootstrap_router)
system_router.include_router(system_config_router)
system_router.include_router(system_diagnostics_router)
system_router.include_router(system_me_router)
system_router.include_router(system_database_router)
