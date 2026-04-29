"""REST v1 版本路由定义。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.routes.dataset_exports import dataset_exports_router
from backend.service.api.rest.v1.routes.datasets import datasets_router
from backend.service.api.rest.v1.routes.models import models_router
from backend.service.api.rest.v1.routes.system import system_router
from backend.service.api.rest.v1.routes.tasks import tasks_router


api_v1_router = APIRouter(prefix="/v1")
api_v1_router.include_router(system_router)
api_v1_router.include_router(datasets_router)
api_v1_router.include_router(dataset_exports_router)
api_v1_router.include_router(models_router)
api_v1_router.include_router(tasks_router)