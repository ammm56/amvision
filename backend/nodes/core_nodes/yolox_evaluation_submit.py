"""YOLOX evaluation task service node。"""

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
    resolve_display_name,
)
from backend.service.application.models.yolox_evaluation_task_service import (
    YoloXEvaluationTaskRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _yolox_evaluation_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用现有 YOLOX evaluation 提交服务。"""

    runtime_context = require_workflow_service_node_runtime(request)
    submission = runtime_context.build_evaluation_task_service().submit_evaluation_task(
        YoloXEvaluationTaskRequest(
            project_id=require_str_parameter(request, "project_id"),
            model_version_id=require_str_parameter(request, "model_version_id"),
            dataset_export_id=get_optional_str_parameter(request, "dataset_export_id"),
            dataset_export_manifest_key=get_optional_str_parameter(request, "dataset_export_manifest_key"),
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            nms_threshold=get_optional_float_parameter(request, "nms_threshold"),
            save_result_package=get_optional_bool_parameter(request, "save_result_package")
            if get_optional_bool_parameter(request, "save_result_package") is not None
            else True,
            extra_options=get_optional_dict_parameter(request, "extra_options"),
        ),
        created_by=resolve_created_by(request),
        display_name=resolve_display_name(request),
    )
    return build_response_body_output(submission)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-evaluation.submit",
        display_name="Submit YOLOX Evaluation",
        category="service.model.evaluation",
        description="按现有 evaluation API 的公开参数直接提交一个评估任务。",
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
                "dataset_export_id": {"type": "string"},
                "dataset_export_manifest_key": {"type": "string"},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "nms_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "save_result_package": {"type": "boolean"},
                "extra_options": {"type": "object"},
                "display_name": {"type": "string"},
                "created_by": {"type": "string"},
            },
            "required": ["project_id", "model_version_id"],
        },
        capability_tags=("service.model.evaluation", "task.submit"),
    ),
    handler=_yolox_evaluation_submit_handler,
)