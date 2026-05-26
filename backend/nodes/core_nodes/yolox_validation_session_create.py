"""YOLOX validation session service node。"""

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
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_float_parameter,
    get_optional_str_parameter,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
)
from backend.service.application.models.yolox_validation_session_service import (
    YoloXValidationSessionCreateRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _yolox_validation_session_create_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """调用现有 YOLOX validation session 创建服务。"""

    runtime_context = require_workflow_service_node_runtime(request)
    session_view = runtime_context.build_validation_session_service().create_session(
        YoloXValidationSessionCreateRequest(
            project_id=require_str_parameter(request, "project_id"),
            model_version_id=require_str_parameter(request, "model_version_id"),
            runtime_profile_id=get_optional_str_parameter(request, "runtime_profile_id"),
            runtime_backend=get_optional_str_parameter(request, "runtime_backend"),
            device_name=get_optional_str_parameter(request, "device_name"),
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            save_result_image=get_optional_bool_parameter(request, "save_result_image")
            if get_optional_bool_parameter(request, "save_result_image") is not None
            else True,
            extra_options=get_optional_dict_parameter(request, "extra_options"),
        ),
        created_by=resolve_created_by(request),
    )
    return build_response_body_output(session_view)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-validation-session.create",
        display_name="Create YOLOX Validation Session",
        category="service.model.validation",
        description="按现有 validation session API 的公开参数创建一个人工验证会话。",
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
                "runtime_profile_id": {"type": "string"},
                "runtime_backend": {"type": "string"},
                "device_name": {"type": "string"},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "save_result_image": {"type": "boolean"},
                "extra_options": {"type": "object"},
                "created_by": {"type": "string"},
            },
            "required": ["project_id", "model_version_id"],
        },
        capability_tags=("service.model.validation", "resource.create"),
    ),
    handler=_yolox_validation_session_create_handler,
)