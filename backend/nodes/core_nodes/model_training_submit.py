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
    build_platform_model_type_parameter_schema,
    build_platform_task_model_type_schema_guards,
    build_platform_task_type_parameter_schema,
    get_supported_platform_model_types,
    require_platform_model_type,
    require_platform_task_type,
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
from backend.service.application.models.training.detection_training_service import (
    resolve_detection_training_service,
)
from backend.service.application.models.training.yolo_primary_classification_training_service import (
    YoloPrimaryClassificationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    Yolo11ClassificationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_obb_training_service import (
    YoloPrimaryObbTrainingTaskRequest,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    Yolo11ObbTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_pose_training_service import (
    YoloPrimaryPoseTrainingTaskRequest,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    Yolo11PoseTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_segmentation_training_service import (
    YoloPrimarySegmentationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    Yolo11SegmentationTrainingTaskRequest,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
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
_NON_DETECTION_TRAINING_REQUEST_BY_TASK_AND_MODEL_TYPE: dict[tuple[str, str], type] = {
    (CLASSIFICATION_TASK_TYPE, "yolo11"): Yolo11ClassificationTrainingTaskRequest,
    (SEGMENTATION_TASK_TYPE, "yolo11"): Yolo11SegmentationTrainingTaskRequest,
    (POSE_TASK_TYPE, "yolo11"): Yolo11PoseTrainingTaskRequest,
    (OBB_TASK_TYPE, "yolo11"): Yolo11ObbTrainingTaskRequest,
}


def _model_training_submit_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """调用统一训练任务 service。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    task_type = require_platform_task_type(request)
    model_type = require_platform_model_type(
        request,
        supported_model_types=get_supported_platform_model_types(task_type),
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
        "dataset_export_manifest_key": get_optional_str_parameter(
            request, "dataset_export_manifest_key"
        ),
        "evaluation_interval": get_optional_int_parameter(
            request, "evaluation_interval"
        ),
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

    request_cls = _NON_DETECTION_TRAINING_REQUEST_BY_TASK_AND_MODEL_TYPE.get(
        (task_type, model_type),
        _NON_DETECTION_TRAINING_REQUEST_BY_TASK_TYPE[task_type],
    )
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
        node_type_id="core.service.model-training.submit",
        display_name="Submit Training",
        category="service.model.training",
        description="按统一 task_type 和 model_type 提交训练任务。",
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
            "required": [
                "task_type",
                "model_type",
                "project_id",
                "recipe_id",
                "model_scale",
                "output_model_name",
            ],
            "allOf": build_platform_task_model_type_schema_guards(),
        },
        capability_tags=("service.model.training", "task.submit"),
    ),
    handler=_model_training_submit_handler,
)
