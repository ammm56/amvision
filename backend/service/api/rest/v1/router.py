"""REST v1 版本路由定义。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.routes.dataset_exports import dataset_exports_router
from backend.service.api.rest.v1.routes.datasets import datasets_router
from backend.service.api.rest.v1.routes.models import models_router
from backend.service.api.rest.v1.routes.system import system_router
from backend.service.api.rest.v1.routes.tasks import tasks_router
from backend.service.api.rest.v1.routes.workflow_runtime import workflow_runtime_router
from backend.service.api.rest.v1.routes.workflow_trigger_sources import workflow_trigger_sources_router
from backend.service.api.rest.v1.routes.workflows import workflows_router
from backend.service.api.rest.v1.routes.yolox_deployments import yolox_deployments_router
from backend.service.api.rest.v1.routes.yolox_conversion_tasks import yolox_conversion_tasks_router
from backend.service.api.rest.v1.routes.yolox_evaluation_tasks import yolox_evaluation_tasks_router
from backend.service.api.rest.v1.routes.yolox_inference_tasks import yolox_inference_tasks_router
from backend.service.api.rest.v1.routes.yolox_training_tasks import yolox_training_tasks_router
from backend.service.api.rest.v1.routes.yolox_validation_sessions import yolox_validation_sessions_router


api_v1_router = APIRouter(prefix="/v1")
api_v1_router.include_router(system_router)
api_v1_router.include_router(workflows_router)
api_v1_router.include_router(workflow_runtime_router)
api_v1_router.include_router(workflow_trigger_sources_router)
api_v1_router.include_router(datasets_router)
api_v1_router.include_router(dataset_exports_router)
api_v1_router.include_router(models_router)
api_v1_router.include_router(yolox_training_tasks_router)
api_v1_router.include_router(yolox_validation_sessions_router)
api_v1_router.include_router(yolox_conversion_tasks_router)
api_v1_router.include_router(yolox_evaluation_tasks_router)
api_v1_router.include_router(yolox_deployments_router)
api_v1_router.include_router(yolox_inference_tasks_router)
api_v1_router.include_router(tasks_router)