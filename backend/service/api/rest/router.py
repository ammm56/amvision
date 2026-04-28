"""REST 根路由定义。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.router import api_v1_router


rest_router = APIRouter(prefix="/api")
rest_router.include_router(api_v1_router)