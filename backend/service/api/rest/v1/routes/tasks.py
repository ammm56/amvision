"""任务 REST 路由分组。"""

from __future__ import annotations

from fastapi import APIRouter


tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])