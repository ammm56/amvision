"""classification deployment 路由组装。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.classification_deployments.services import (
    CLASSIFICATION_DEPLOYMENT_ROUTE_CONFIG,
)
from backend.service.api.rest.v1.routes.task_deployments.factory import create_task_deployment_router


classification_deployments_router = create_task_deployment_router(CLASSIFICATION_DEPLOYMENT_ROUTE_CONFIG)
