"""segmentation deployment route service 装配。"""

from __future__ import annotations

from backend.service.api.deps.segmentation_deployment_process_supervisor import (
    get_segmentation_async_deployment_process_supervisor,
    get_segmentation_async_inference_gateway_dispatcher_registry,
    get_segmentation_sync_deployment_process_supervisor,
)
from backend.service.api.rest.v1.routes.segmentation_deployments.responses import (
    build_segmentation_deployment_instance_response,
)
from backend.service.api.rest.v1.routes.segmentation_deployments.schemas import (
    SegmentationDeploymentInstanceCreateRequestBody,
    SegmentationDeploymentInstanceResponse,
)
from backend.service.api.rest.v1.routes.task_deployments.factory import TaskDeploymentRouteConfig
from backend.service.application.deployments.segmentation_deployment_service import (
    SegmentationDeploymentInstanceCreateRequest,
    SqlAlchemySegmentationDeploymentService,
)


SEGMENTATION_DEPLOYMENT_ROUTE_CONFIG = TaskDeploymentRouteConfig(
    route_segment="segmentation",
    create_body_model=SegmentationDeploymentInstanceCreateRequestBody,
    instance_response_model=SegmentationDeploymentInstanceResponse,
    service_cls=SqlAlchemySegmentationDeploymentService,
    create_request_cls=SegmentationDeploymentInstanceCreateRequest,
    response_builder=build_segmentation_deployment_instance_response,
    sync_supervisor_dependency=get_segmentation_sync_deployment_process_supervisor,
    async_supervisor_dependency=get_segmentation_async_deployment_process_supervisor,
    async_gateway_dispatcher_registry_dependency=get_segmentation_async_inference_gateway_dispatcher_registry,
)
