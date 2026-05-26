"""YOLOX training task service node。"""

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
    get_optional_int_pair_parameter,
    get_optional_int_parameter,
    get_optional_str_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
    resolve_display_name,
)
from backend.service.application.models.yolox_training_service import YoloXTrainingTaskRequest
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _yolox_training_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用现有 YOLOX training 提交服务。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    submission = runtime_context.build_training_task_service().submit_training_task(
        YoloXTrainingTaskRequest(
            project_id=require_str_parameter(request, "project_id"),
            recipe_id=require_str_parameter(request, "recipe_id"),
            model_scale=require_str_parameter(request, "model_scale"),
            output_model_name=require_str_parameter(request, "output_model_name"),
            dataset_export_id=get_optional_str_parameter(request, "dataset_export_id"),
            dataset_export_manifest_key=get_optional_str_parameter(request, "dataset_export_manifest_key"),
            warm_start_model_version_id=get_optional_str_parameter(request, "warm_start_model_version_id"),
            evaluation_interval=get_optional_int_parameter(request, "evaluation_interval"),
            max_epochs=get_optional_int_parameter(request, "max_epochs"),
            batch_size=get_optional_int_parameter(request, "batch_size"),
            gpu_count=get_optional_int_parameter(request, "gpu_count"),
            precision=get_optional_str_parameter(request, "precision"),
            input_size=get_optional_int_pair_parameter(request, "input_size"),
            extra_options=get_optional_dict_parameter(request, "extra_options"),
        ),
        created_by=resolve_created_by(request),
        display_name=resolve_display_name(request),
    )
    return build_response_body_output(submission)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-training.submit",
        display_name="Submit YOLOX Training",
        category="service.model.training",
        description="按现有 training API 的公开参数直接提交一个训练任务。",
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
                "project_id": {"type": "string"},
                "dataset_export_id": {"type": "string"},
                "dataset_export_manifest_key": {"type": "string"},
                "recipe_id": {"type": "string"},
                "model_scale": {"type": "string", "enum": ["nano", "tiny", "s", "m", "l", "x"]},
                "output_model_name": {"type": "string"},
                "warm_start_model_version_id": {"type": "string"},
                "evaluation_interval": {"type": "integer", "minimum": 1},
                "max_epochs": {"type": "integer", "minimum": 1},
                "batch_size": {"type": "integer", "minimum": 1},
                "gpu_count": {"type": "integer", "minimum": 1},
                "precision": {"type": "string", "enum": ["fp16", "fp32"]},
                "input_size": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "extra_options": {"type": "object"},
                "display_name": {"type": "string"},
                "created_by": {"type": "string"},
            },
            "required": ["project_id", "recipe_id", "model_scale", "output_model_name"],
        },
        capability_tags=("service.model.training", "task.submit"),
    ),
    handler=_yolox_training_submit_handler,
)