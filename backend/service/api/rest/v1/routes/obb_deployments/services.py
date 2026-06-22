"""OBB deployment route service 装配。"""

from __future__ import annotations

from backend.service.api.deps.obb_deployment_process_supervisor import (
    get_obb_async_deployment_process_supervisor,
    get_obb_async_inference_gateway_dispatcher_registry,
    get_obb_sync_deployment_process_supervisor,
)
from backend.service.api.rest.v1.routes.obb_deployments.responses import (
    build_obb_deployment_instance_response,
)
from backend.service.api.rest.v1.routes.obb_deployments.schemas import (
    ObbDeploymentInstanceCreateRequestBody,
    ObbDeploymentInstanceResponse,
)
from backend.service.api.rest.v1.routes.task_deployments.factory import TaskDeploymentRouteConfig
from backend.service.application.deployments.obb_deployment_service import (
    ObbDeploymentInstanceCreateRequest,
    SqlAlchemyObbDeploymentService,
)


OBB_DEPLOYMENT_ROUTE_CONFIG = TaskDeploymentRouteConfig(
    route_segment="obb",
    create_body_model=ObbDeploymentInstanceCreateRequestBody,
    instance_response_model=ObbDeploymentInstanceResponse,
    service_cls=SqlAlchemyObbDeploymentService,
    create_request_cls=ObbDeploymentInstanceCreateRequest,
    response_builder=build_obb_deployment_instance_response,
    sync_supervisor_dependency=get_obb_sync_deployment_process_supervisor,
    async_supervisor_dependency=get_obb_async_deployment_process_supervisor,
    async_gateway_dispatcher_registry_dependency=get_obb_async_inference_gateway_dispatcher_registry,
)
