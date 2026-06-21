"""评估任务提交 service node。"""

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
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
    resolve_display_name,
)
from backend.service.application.models.evaluation.detection_evaluation_task_service import (
    DetectionEvaluationTaskRequest,
)
from backend.service.application.models.evaluation.obb_evaluation_task_service import (
    ObbEvaluationTaskRequest,
)
from backend.service.application.models.evaluation.pose_evaluation_task_service import (
    PoseEvaluationTaskRequest,
)
from backend.service.application.models.evaluation.yolo_primary_classification_evaluation_task_service import (
    YoloPrimaryClassificationEvaluationTaskRequest,
)
from backend.service.application.models.evaluation.yolo_primary_segmentation_evaluation_task_service import (
    YoloPrimarySegmentationEvaluationTaskRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


def _model_evaluation_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用统一评估任务 service。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    task_type = require_platform_task_type(request)
    model_type = require_platform_model_type(request)
    submission = runtime_context.build_evaluation_task_service(
        task_type=task_type,
    ).submit_evaluation_task(
        _build_platform_evaluation_request(
            request,
            task_type=task_type,
            model_type=model_type,
        ),
        created_by=resolve_created_by(request),
        display_name=resolve_display_name(request),
    )
    return build_response_body_output(submission)


def _build_platform_evaluation_request(
    request: WorkflowNodeExecutionRequest,
    *,
    task_type: str,
    model_type: str,
) -> object:
    """按 task_type 构造正式评估请求。"""

    common_kwargs = {
        "project_id": require_str_parameter(request, "project_id"),
        "model_version_id": require_str_parameter(request, "model_version_id"),
        "dataset_export_id": get_optional_str_parameter(request, "dataset_export_id"),
        "dataset_export_manifest_key": get_optional_str_parameter(request, "dataset_export_manifest_key"),
        "save_result_package": get_optional_bool_parameter(request, "save_result_package")
        if get_optional_bool_parameter(request, "save_result_package") is not None
        else True,
        "extra_options": get_optional_dict_parameter(request, "extra_options"),
    }
    if task_type == DETECTION_TASK_TYPE:
        return DetectionEvaluationTaskRequest(
            **common_kwargs,
            model_type=model_type,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            nms_threshold=get_optional_float_parameter(request, "nms_threshold"),
        )
    if task_type == CLASSIFICATION_TASK_TYPE:
        return YoloPrimaryClassificationEvaluationTaskRequest(
            **common_kwargs,
            top_k=get_optional_int_parameter(request, "top_k") or 5,
        )
    if task_type == SEGMENTATION_TASK_TYPE:
        return YoloPrimarySegmentationEvaluationTaskRequest(
            **common_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            mask_threshold=get_optional_float_parameter(request, "mask_threshold"),
        )
    if task_type == POSE_TASK_TYPE:
        return PoseEvaluationTaskRequest(
            **common_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold") or 0.01,
        )
    return ObbEvaluationTaskRequest(
        **common_kwargs,
        score_threshold=get_optional_float_parameter(request, "score_threshold") or 0.01,
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.model-evaluation.submit",
        display_name="Submit Evaluation",
        category="service.model.evaluation",
        description="按统一 task_type 提交评估任务。",
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
                "task_type": {"type": "string", "enum": list(WORKFLOW_SERVICE_TASK_TYPES)},
                "model_type": {"type": "string"},
                "project_id": {"type": "string"},
                "model_version_id": {"type": "string"},
                "dataset_export_id": {"type": "string"},
                "dataset_export_manifest_key": {"type": "string"},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "nms_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "mask_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "top_k": {"type": "integer", "minimum": 1},
                "save_result_package": {"type": "boolean"},
                "extra_options": {"type": "object"},
                "display_name": {"type": "string"},
                "created_by": {"type": "string"},
            },
            "required": ["task_type", "model_type", "project_id", "model_version_id"],
        },
        capability_tags=("service.model.evaluation", "task.submit"),
    ),
    handler=_model_evaluation_submit_handler,
)
