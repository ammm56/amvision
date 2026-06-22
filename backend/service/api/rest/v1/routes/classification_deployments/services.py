"""classification deployment route service 装配。"""

from __future__ import annotations

from backend.service.api.deps.classification_deployment_process_supervisor import (
    get_classification_async_deployment_process_supervisor,
    get_classification_async_inference_gateway_dispatcher_registry,
    get_classification_sync_deployment_process_supervisor,
)
from backend.service.api.rest.v1.routes.classification_deployments.responses import (
    build_classification_deployment_instance_response,
)
from backend.service.api.rest.v1.routes.classification_deployments.schemas import (
    ClassificationDeploymentInstanceCreateRequestBody,
    ClassificationDeploymentInstanceResponse,
)
from backend.service.api.rest.v1.routes.task_deployments.factory import TaskDeploymentRouteConfig
from backend.service.application.deployments.classification_deployment_service import (
    ClassificationDeploymentInstanceCreateRequest,
    SqlAlchemyClassificationDeploymentService,
)


CLASSIFICATION_DEPLOYMENT_ROUTE_CONFIG = TaskDeploymentRouteConfig(
    route_segment="classification",
    create_body_model=ClassificationDeploymentInstanceCreateRequestBody,
    instance_response_model=ClassificationDeploymentInstanceResponse,
    service_cls=SqlAlchemyClassificationDeploymentService,
    create_request_cls=ClassificationDeploymentInstanceCreateRequest,
    response_builder=build_classification_deployment_instance_response,
    sync_supervisor_dependency=get_classification_sync_deployment_process_supervisor,
    async_supervisor_dependency=get_classification_async_deployment_process_supervisor,
    async_gateway_dispatcher_registry_dependency=get_classification_async_inference_gateway_dispatcher_registry,
)
