"""模型 REST 路由分组。"""

from __future__ import annotations

from fastapi import APIRouter


models_router = APIRouter(prefix="/models", tags=["models"])