"""detection deployment 路由组装。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.routes.detection_deployments.async_runtime import (
    detection_deployment_async_router,
)
from backend.service.api.rest.v1.routes.detection_deployments.events import detection_deployment_events_router
from backend.service.api.rest.v1.routes.detection_deployments.instances import (
    detection_deployment_instances_router,
)
from backend.service.api.rest.v1.routes.detection_deployments.sync import detection_deployment_sync_router


detection_deployments_router = APIRouter(prefix="/models", tags=["models"])
detection_deployments_router.include_router(detection_deployment_instances_router)
detection_deployments_router.include_router(detection_deployment_events_router)
detection_deployments_router.include_router(detection_deployment_sync_router)
detection_deployments_router.include_router(detection_deployment_async_router)
