"""pose deployment route service 装配。"""

from __future__ import annotations

from backend.service.api.deps.pose_deployment_process_supervisor import (
    get_pose_async_deployment_process_supervisor,
    get_pose_async_inference_gateway_dispatcher_registry,
    get_pose_sync_deployment_process_supervisor,
)
from backend.service.api.rest.v1.routes.pose_deployments.responses import (
    build_pose_deployment_instance_response,
)
from backend.service.api.rest.v1.routes.pose_deployments.schemas import (
    PoseDeploymentInstanceCreateRequestBody,
    PoseDeploymentInstanceResponse,
)
from backend.service.api.rest.v1.routes.task_deployments.factory import TaskDeploymentRouteConfig
from backend.service.application.deployments.pose_deployment_service import (
    PoseDeploymentInstanceCreateRequest,
    SqlAlchemyPoseDeploymentService,
)


POSE_DEPLOYMENT_ROUTE_CONFIG = TaskDeploymentRouteConfig(
    route_segment="pose",
    create_body_model=PoseDeploymentInstanceCreateRequestBody,
    instance_response_model=PoseDeploymentInstanceResponse,
    service_cls=SqlAlchemyPoseDeploymentService,
    create_request_cls=PoseDeploymentInstanceCreateRequest,
    response_builder=build_pose_deployment_instance_response,
    sync_supervisor_dependency=get_pose_sync_deployment_process_supervisor,
    async_supervisor_dependency=get_pose_async_deployment_process_supervisor,
    async_gateway_dispatcher_registry_dependency=get_pose_async_inference_gateway_dispatcher_registry,
)
