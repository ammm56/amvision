"""数据集 REST 路由分组。"""

from __future__ import annotations

from fastapi import APIRouter


datasets_router = APIRouter(prefix="/datasets", tags=["datasets"])