"""训练任务提交 service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._platform_service_node_support import (
    WORKFLOW_SERVICE_MODEL_SCALES,
    WORKFLOW_SERVICE_TASK_TYPES,
    get_optional_platform_model_type,
    get_optional_platform_task_type,
    resolve_platform_model_type,
    resolve_platform_task_type,
    should_use_platform_service_routing,
)
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
from backend.service.application.models.detection_training_service import (
    resolve_detection_training_service,
)
from backend.service.application.models.yolo_primary_classification_training_service import (
    YoloPrimaryClassificationTrainingTaskRequest,
)
from backend.service.application.models.yolo_primary_obb_training_service import (
    YoloPrimaryObbTrainingTaskRequest,
)
from backend.service.application.models.yolo_primary_pose_training_service import (
    YoloPrimaryPoseTrainingTaskRequest,
)
from backend.service.application.models.yolo_primary_segmentation_training_service import (
    YoloPrimarySegmentationTrainingTaskRequest,
)
from backend.service.application.models.yolox_training_service import (
    YoloXTrainingTaskRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


_NON_DETECTION_TRAINING_REQUEST_BY_TASK_TYPE: dict[str, type] = {
    CLASSIFICATION_TASK_TYPE: YoloPrimaryClassificationTrainingTaskRequest,
    SEGMENTATION_TASK_TYPE: YoloPrimarySegmentationTrainingTaskRequest,
    POSE_TASK_TYPE: YoloPrimaryPoseTrainingTaskRequest,
    OBB_TASK_TYPE: YoloPrimaryObbTrainingTaskRequest,
}


def _model_training_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用训练任务 service，兼容旧 YOLOX 节点参数并支持显式 task_type/model_type。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    requested_task_type = get_optional_platform_task_type(request)
    requested_model_type = get_optional_platform_model_type(
        request,
        supported_model_types=("yolox", "yolov8", "yolo11", "yolo26", "rfdetr"),
    )
    use_platform_routing = should_use_platform_service_routing(
        task_type=requested_task_type,
        model_type=requested_model_type,
    )
    if not use_platform_routing:
        submission = runtime_context.build_training_task_service().submit_training_task(
            _build_legacy_yolox_training_request(request),
            created_by=resolve_created_by(request),
            display_name=resolve_display_name(request),
        )
        return build_response_body_output(submission)

    task_type = resolve_platform_task_type(
        requested_task_type,
        default_task_type=DETECTION_TASK_TYPE,
    )
    model_type = resolve_platform_model_type(
        requested_model_type,
        task_type=task_type,
    )
    service = runtime_context.build_training_task_service(
        task_type=task_type,
        model_type=model_type,
    )
    training_request, submit_kwargs = _build_platform_training_request(
        request,
        task_type=task_type,
        model_type=model_type,
    )
    submission = service.submit_training_task(
        training_request,
        created_by=resolve_created_by(request),
        **submit_kwargs,
    )
    return build_response_body_output(submission)


def _build_legacy_yolox_training_request(
    request: WorkflowNodeExecutionRequest,
) -> YoloXTrainingTaskRequest:
    """构造旧 YOLOX detection 训练请求。"""

    return YoloXTrainingTaskRequest(
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
    )


def _build_platform_training_request(
    request: WorkflowNodeExecutionRequest,
    *,
    task_type: str,
    model_type: str,
) -> tuple[object, dict[str, object]]:
    """按 task_type/model_type 构造正式训练请求。"""

    common_kwargs = {
        "project_id": require_str_parameter(request, "project_id"),
        "recipe_id": require_str_parameter(request, "recipe_id"),
        "model_scale": require_str_parameter(request, "model_scale"),
        "output_model_name": require_str_parameter(request, "output_model_name"),
        "dataset_export_id": get_optional_str_parameter(request, "dataset_export_id"),
        "dataset_export_manifest_key": get_optional_str_parameter(request, "dataset_export_manifest_key"),
        "evaluation_interval": get_optional_int_parameter(request, "evaluation_interval"),
        "max_epochs": get_optional_int_parameter(request, "max_epochs"),
        "batch_size": get_optional_int_parameter(request, "batch_size"),
        "precision": get_optional_str_parameter(request, "precision"),
        "input_size": get_optional_int_pair_parameter(request, "input_size"),
        "extra_options": get_optional_dict_parameter(request, "extra_options"),
    }
    display_name = resolve_display_name(request)
    if task_type == DETECTION_TASK_TYPE:
        _, request_cls, _ = resolve_detection_training_service(model_type)
        return (
            request_cls(
                **common_kwargs,
                warm_start_model_version_id=get_optional_str_parameter(
                    request, "warm_start_model_version_id"
                ),
                gpu_count=get_optional_int_parameter(request, "gpu_count"),
            ),
            {"display_name": display_name},
        )

    request_cls = _NON_DETECTION_TRAINING_REQUEST_BY_TASK_TYPE[task_type]
    return (
        request_cls(
            **common_kwargs,
            display_name=display_name,
            model_type=model_type,
        ),
        {},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-training.submit",
        display_name="Submit Training",
        category="service.model.training",
        description="兼容旧 YOLOX 节点名，同时支持按 task_type 和 model_type 提交正式训练任务。",
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
                "model_type": {
                    "type": "string",
                    "enum": ["yolox", "yolov8", "yolo11", "yolo26", "rfdetr"],
                },
                "project_id": {"type": "string"},
                "dataset_export_id": {"type": "string"},
                "dataset_export_manifest_key": {"type": "string"},
                "recipe_id": {"type": "string"},
                "model_scale": {
                    "type": "string",
                    "enum": list(WORKFLOW_SERVICE_MODEL_SCALES),
                },
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
    handler=_model_training_submit_handler,
)
