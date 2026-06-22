"""数据集 API 聚合路由。"""

from __future__ import annotations

from fastapi import APIRouter

from .exports import dataset_exports_router
from .imports import dataset_imports_router


datasets_router = APIRouter(prefix="/datasets", tags=["datasets"])
datasets_router.include_router(dataset_imports_router)
datasets_router.include_router(dataset_exports_router)
