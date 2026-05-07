"""YOLOX deployment create service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._service_node_support import (
    build_response_body_output,
    get_optional_dict_parameter,
    get_optional_int_parameter,
    get_optional_str_parameter,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
)
from backend.service.application.deployments.yolox_deployment_service import (
    YoloXDeploymentInstanceCreateRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _yolox_deployment_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用现有 DeploymentInstance 创建服务。"""

    runtime_context = require_workflow_service_node_runtime(request)
    view = runtime_context.build_deployment_service().create_deployment_instance(
        YoloXDeploymentInstanceCreateRequest(
            project_id=require_str_parameter(request, "project_id"),
            model_version_id=get_optional_str_parameter(request, "model_version_id"),
            model_build_id=get_optional_str_parameter(request, "model_build_id"),
            runtime_profile_id=get_optional_str_parameter(request, "runtime_profile_id"),
            runtime_backend=get_optional_str_parameter(request, "runtime_backend"),
            device_name=get_optional_str_parameter(request, "device_name"),
            runtime_precision=get_optional_str_parameter(request, "runtime_precision"),
            instance_count=get_optional_int_parameter(request, "instance_count") or 1,
            display_name=get_optional_str_parameter(request, "display_name") or "",
            metadata=get_optional_dict_parameter(request, "metadata"),
        ),
        created_by=resolve_created_by(request),
    )
    return build_response_body_output(view)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-deployment.create",
        display_name="Create YOLOX Deployment",
        category="service.model.deployment.resource",
        description="按现有 deployment create API 的公开参数创建一个 DeploymentInstance 资源。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        output_ports=(
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "model_version_id": {"type": "string"},
                "model_build_id": {"type": "string"},
                "runtime_profile_id": {"type": "string"},
                "runtime_backend": {"type": "string"},
                "device_name": {"type": "string"},
                "runtime_precision": {"type": "string"},
                "instance_count": {"type": "integer", "minimum": 1},
                "display_name": {"type": "string"},
                "metadata": {"type": "object"},
                "created_by": {"type": "string"},
            },
            "required": ["project_id"],
            "anyOf": [
                {"required": ["model_version_id"]},
                {"required": ["model_build_id"]}
            ],
        },
        capability_tags=("service.model.deployment", "resource.create", "resource.control-plane"),
    ),
    handler=_yolox_deployment_create_handler,
)