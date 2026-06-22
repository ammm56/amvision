"""segmentation deployment 路由组装。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.segmentation_deployments.services import (
    SEGMENTATION_DEPLOYMENT_ROUTE_CONFIG,
)
from backend.service.api.rest.v1.routes.task_deployments.factory import create_task_deployment_router


segmentation_deployments_router = create_task_deployment_router(SEGMENTATION_DEPLOYMENT_ROUTE_CONFIG)
