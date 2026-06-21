"""转换任务提交 service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._platform_service_node_support import (
    build_platform_model_type_parameter_schema,
    build_platform_task_model_type_schema_guards,
    build_platform_task_type_parameter_schema,
    get_supported_platform_model_types,
    require_platform_model_type,
    require_platform_task_type,
)
from backend.service.application.conversions.yolox_conversion_task_service import (
    YoloXConversionTaskRequest,
)
from backend.nodes.core_nodes._service_node_support import (
    build_response_body_output,
    get_optional_dict_parameter,
    get_optional_str_parameter,
    get_optional_str_tuple_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
    resolve_display_name,
)
from backend.service.application.conversions.yolo_model_conversion_task_service import (
    YoloConversionTaskRequest,
)
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    RfdetrConversionTaskRequest,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE


def _model_conversion_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用统一转换任务 service。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    target_formats = get_optional_str_tuple_parameter(request, "target_formats")
    if target_formats is None or not target_formats:
        raise InvalidRequestError(
            "target_formats 至少需要一个目标格式",
            details={"node_id": request.node_id, "parameter": "target_formats"},
        )

    task_type = require_platform_task_type(request)
    model_type = require_platform_model_type(
        request,
        supported_model_types=get_supported_platform_model_types(task_type),
    )
    if task_type == DETECTION_TASK_TYPE and model_type == "yolox":
        request_cls = YoloXConversionTaskRequest
    elif task_type == DETECTION_TASK_TYPE and model_type == "rfdetr":
        request_cls = RfdetrConversionTaskRequest
    else:
        request_cls = YoloConversionTaskRequest
    request_kwargs = {
        "project_id": require_str_parameter(request, "project_id"),
        "source_model_version_id": require_str_parameter(request, "source_model_version_id"),
        "target_formats": target_formats,
        "runtime_profile_id": get_optional_str_parameter(request, "runtime_profile_id"),
        "extra_options": get_optional_dict_parameter(request, "extra_options"),
    }
    if request_cls is RfdetrConversionTaskRequest:
        request_kwargs["task_type"] = task_type
    submission = runtime_context.build_conversion_task_service(
        task_type=task_type,
        model_type=model_type,
    ).submit_conversion_task(
        request_cls(**request_kwargs),
        created_by=resolve_created_by(request),
        display_name=resolve_display_name(request),
    )
    return build_response_body_output(submission)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.model-conversion.submit",
        display_name="Submit Conversion",
        category="service.model.conversion",
        description="按统一 task_type 和 model_type 提交转换任务。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="request",
                display_name="Request",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
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
                "task_type": build_platform_task_type_parameter_schema(),
                "model_type": build_platform_model_type_parameter_schema(),
                "project_id": {"type": "string"},
                "source_model_version_id": {"type": "string"},
                "target_formats": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine", "rknn"],
                    },
                },
                "runtime_profile_id": {"type": "string"},
                "extra_options": {"type": "object"},
                "display_name": {"type": "string"},
                "created_by": {"type": "string"},
            },
            "required": ["task_type", "model_type", "project_id", "source_model_version_id", "target_formats"],
            "allOf": build_platform_task_model_type_schema_guards(),
        },
        capability_tags=("service.model.conversion", "task.submit"),
    ),
    handler=_model_conversion_submit_handler,
)
