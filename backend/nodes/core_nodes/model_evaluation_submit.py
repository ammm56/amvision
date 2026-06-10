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
    get_optional_platform_task_type,
    resolve_platform_task_type,
    should_use_platform_service_routing,
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
from backend.service.application.models.detection_evaluation_task_service import (
    DetectionEvaluationTaskRequest,
)
from backend.service.application.models.obb_evaluation_task_service import (
    ObbEvaluationTaskRequest,
)
from backend.service.application.models.pose_evaluation_task_service import (
    PoseEvaluationTaskRequest,
)
from backend.service.application.models.yolo_primary_classification_evaluation_task_service import (
    ClassificationEvaluationTaskRequest,
)
from backend.service.application.models.yolo_primary_segmentation_evaluation_task_service import (
    SegmentationEvaluationTaskRequest,
)
from backend.service.application.models.yolox_evaluation_task_service import (
    YoloXEvaluationTaskRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


def _model_evaluation_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用评估任务 service，兼容旧 YOLOX 节点名并支持显式平台路由。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    requested_task_type = get_optional_platform_task_type(request)
    use_platform_routing = should_use_platform_service_routing(
        task_type=requested_task_type,
        model_type=None,
    )
    if not use_platform_routing:
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

    task_type = resolve_platform_task_type(
        requested_task_type,
        default_task_type=DETECTION_TASK_TYPE,
    )
    submission = runtime_context.build_evaluation_task_service(
        task_type=task_type,
    ).submit_evaluation_task(
        _build_platform_evaluation_request(request, task_type=task_type),
        created_by=resolve_created_by(request),
        display_name=resolve_display_name(request),
    )
    return build_response_body_output(submission)


def _build_platform_evaluation_request(
    request: WorkflowNodeExecutionRequest,
    *,
    task_type: str,
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
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            nms_threshold=get_optional_float_parameter(request, "nms_threshold"),
        )
    if task_type == CLASSIFICATION_TASK_TYPE:
        return ClassificationEvaluationTaskRequest(
            **common_kwargs,
            top_k=get_optional_int_parameter(request, "top_k") or 5,
        )
    if task_type == SEGMENTATION_TASK_TYPE:
        return SegmentationEvaluationTaskRequest(
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
        node_type_id="core.service.yolox-evaluation.submit",
        display_name="Submit Evaluation",
        category="service.model.evaluation",
        description="兼容旧 YOLOX 节点名，同时支持按 task_type 提交正式评估任务。",
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
            "required": ["project_id", "model_version_id"],
        },
        capability_tags=("service.model.evaluation", "task.submit"),
    ),
    handler=_model_evaluation_submit_handler,
)
