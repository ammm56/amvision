"""pose deployment 路由组装。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.pose_deployments.services import POSE_DEPLOYMENT_ROUTE_CONFIG
from backend.service.api.rest.v1.routes.task_deployments.factory import create_task_deployment_router


pose_deployments_router = create_task_deployment_router(POSE_DEPLOYMENT_ROUTE_CONFIG)
