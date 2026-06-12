"""人工验证 session 创建 service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._platform_service_node_support import (
    WORKFLOW_SERVICE_TASK_TYPES,
    require_platform_model_type,
    require_platform_task_type,
)
from backend.nodes.core_nodes._service_node_support import (
    build_response_body_output,
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_float_parameter,
    get_optional_int_parameter,
    get_optional_str_parameter,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
)
from backend.service.application.models.classification_validation_session_service import (
    ClassificationValidationSessionCreateRequest,
)
from backend.service.application.models.detection_validation_session_service import (
    DetectionValidationSessionCreateRequest,
)
from backend.service.application.models.obb_validation_session_service import (
    ObbValidationSessionCreateRequest,
)
from backend.service.application.models.pose_validation_session_service import (
    PoseValidationSessionCreateRequest,
)
from backend.service.application.models.segmentation_validation_session_service import (
    SegmentationValidationSessionCreateRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


def _model_validation_session_create_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """调用统一 validation session 创建服务。"""

    runtime_context = require_workflow_service_node_runtime(request)
    task_type = require_platform_task_type(request)
    model_type = require_platform_model_type(request)
    session_view = runtime_context.build_validation_session_service(
        task_type=task_type,
    ).create_session(
        _build_platform_validation_request(
            request,
            task_type=task_type,
            model_type=model_type,
        ),
        created_by=resolve_created_by(request),
    )
    return build_response_body_output(session_view)


def _build_platform_validation_request(
    request: WorkflowNodeExecutionRequest,
    *,
    task_type: str,
    model_type: str,
) -> object:
    """按 task_type/model_type 构造正式 validation session 创建请求。"""

    common_kwargs = {
        "project_id": require_str_parameter(request, "project_id"),
        "model_type": model_type,
        "model_version_id": require_str_parameter(request, "model_version_id"),
        "runtime_profile_id": get_optional_str_parameter(request, "runtime_profile_id"),
        "runtime_backend": get_optional_str_parameter(request, "runtime_backend"),
        "device_name": get_optional_str_parameter(request, "device_name"),
        "save_result_image": get_optional_bool_parameter(request, "save_result_image")
        if get_optional_bool_parameter(request, "save_result_image") is not None
        else True,
        "extra_options": get_optional_dict_parameter(request, "extra_options"),
    }
    if task_type == DETECTION_TASK_TYPE:
        return DetectionValidationSessionCreateRequest(
            **common_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
        )
    if task_type == CLASSIFICATION_TASK_TYPE:
        return ClassificationValidationSessionCreateRequest(
            **common_kwargs,
            top_k=get_optional_int_parameter(request, "top_k"),
        )
    if task_type == SEGMENTATION_TASK_TYPE:
        return SegmentationValidationSessionCreateRequest(
            **common_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            mask_threshold=get_optional_float_parameter(request, "mask_threshold"),
        )
    if task_type == POSE_TASK_TYPE:
        return PoseValidationSessionCreateRequest(
            **common_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            keypoint_confidence_threshold=get_optional_float_parameter(
                request,
                "keypoint_confidence_threshold",
            ),
        )
    return ObbValidationSessionCreateRequest(
        **common_kwargs,
        score_threshold=get_optional_float_parameter(request, "score_threshold"),
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.model-validation-session.create",
        display_name="Create Validation Session",
        category="service.model.validation",
        description="按统一 task_type 和 model_type 创建人工验证会话。",
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
                "task_type": {"type": "string", "enum": list(WORKFLOW_SERVICE_TASK_TYPES)},
                "model_type": {
                    "type": "string",
                    "enum": ["yolox", "yolov8", "yolo11", "yolo26", "rfdetr"],
                },
                "project_id": {"type": "string"},
                "model_version_id": {"type": "string"},
                "runtime_profile_id": {"type": "string"},
                "runtime_backend": {"type": "string"},
                "device_name": {"type": "string"},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "mask_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "keypoint_confidence_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "top_k": {"type": "integer", "minimum": 1},
                "save_result_image": {"type": "boolean"},
                "extra_options": {"type": "object"},
                "created_by": {"type": "string"},
            },
            "required": ["task_type", "model_type", "project_id", "model_version_id"],
        },
        capability_tags=("service.model.validation", "resource.create"),
    ),
    handler=_model_validation_session_create_handler,
)
