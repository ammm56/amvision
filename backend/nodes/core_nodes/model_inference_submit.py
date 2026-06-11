"""inference task service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._platform_service_node_support import (
    get_optional_platform_model_type,
    get_optional_platform_task_type,
    get_supported_platform_model_types,
    resolve_platform_task_type,
)
from backend.nodes.core_nodes._service_node_support import (
    build_service_node_deployment_service,
    build_service_node_inference_task_service,
    build_response_body_output,
    ensure_running_deployment_process,
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_float_parameter,
    get_optional_image_object_key,
    get_optional_int_parameter,
    get_optional_str_parameter,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
    resolve_display_name,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.classification_inference_task_service import (
    ClassificationInferenceTaskRequest,
)
from backend.service.application.models.detection_inference_task_service import (
    DetectionInferenceTaskRequest,
)
from backend.service.application.models.obb_inference_task_service import (
    ObbInferenceTaskRequest,
)
from backend.service.application.models.pose_inference_task_service import (
    PoseInferenceTaskRequest,
)
from backend.service.application.models.segmentation_inference_task_service import (
    SegmentationInferenceTaskRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE


def _model_inference_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用正式平台 inference task 提交服务。"""

    runtime_context = require_workflow_service_node_runtime(request)
    task_type = resolve_platform_task_type(
        get_optional_platform_task_type(request),
        default_task_type=DETECTION_TASK_TYPE,
    )
    deployment_service = build_service_node_deployment_service(
        runtime_context,
        task_type=task_type,
    )
    project_id = require_str_parameter(request, "project_id")
    deployment_instance_id = require_str_parameter(request, "deployment_instance_id")
    deployment_view = deployment_service.get_deployment_instance(deployment_instance_id)
    if deployment_view.project_id != project_id:
        raise InvalidRequestError(
            "deployment_instance_id 与 project_id 不匹配",
            details={
                "project_id": project_id,
                "deployment_project_id": deployment_view.project_id,
                "deployment_instance_id": deployment_instance_id,
            },
        )
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    deployment_process_supervisor = runtime_context.require_async_deployment_process_supervisor(
        task_type=task_type
    )
    deployment_process_supervisor.ensure_deployment(process_config)
    auto_start_process = get_optional_bool_parameter(request, "auto_start_process")
    ensure_running_deployment_process(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        runtime_mode="async",
        auto_start_process=True if auto_start_process is None else auto_start_process,
    )

    image_object_key = get_optional_image_object_key(request)
    normalized_input_uri = image_object_key or get_optional_str_parameter(request, "input_uri")
    input_file_id = get_optional_str_parameter(request, "input_file_id")
    input_source_kind = "input_uri"
    if input_file_id is not None and normalized_input_uri is None:
        input_source_kind = "input_file_id"

    submission = build_service_node_inference_task_service(
        runtime_context,
        task_type=task_type,
    ).submit_inference_task(
        _build_inference_task_request(
            request=request,
            task_type=task_type,
            project_id=project_id,
            deployment_instance_id=deployment_instance_id,
            input_file_id=input_file_id,
            input_uri=normalized_input_uri,
            input_source_kind=input_source_kind,
            async_inference_owner_id=runtime_context.async_inference_service_id,
        ),
        created_by=resolve_created_by(request),
        display_name=resolve_display_name(request),
    )
    return build_response_body_output(
        {
            "task_id": submission.task_id,
            "status": submission.status,
            "queue_name": submission.queue_name,
            "queue_task_id": submission.queue_task_id,
            "deployment_instance_id": submission.deployment_instance_id,
            "input_uri": submission.input_uri,
            "input_source_kind": input_source_kind,
        }
    )


def _build_inference_task_request(
    *,
    request: WorkflowNodeExecutionRequest,
    task_type: str,
    project_id: str,
    deployment_instance_id: str,
    input_file_id: str | None,
    input_uri: str | None,
    input_source_kind: str,
    async_inference_owner_id: str | None,
):
    """按 task_type 构造对应的 inference task request。"""

    model_type = get_optional_platform_model_type(
        request,
        supported_model_types=get_supported_platform_model_types(task_type),
    )
    shared_kwargs = {
        "project_id": project_id,
        "deployment_instance_id": deployment_instance_id,
        "model_type": model_type,
        "input_file_id": input_file_id,
        "input_uri": input_uri,
        "input_source_kind": input_source_kind,
        "async_inference_owner_id": async_inference_owner_id,
        "save_result_image": bool(get_optional_bool_parameter(request, "save_result_image") is True),
        "return_preview_image_base64": bool(
            get_optional_bool_parameter(request, "return_preview_image_base64") is True
        ),
        "extra_options": get_optional_dict_parameter(request, "extra_options") or {},
    }
    if task_type == DETECTION_TASK_TYPE:
        return DetectionInferenceTaskRequest(
            **shared_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
        )
    if task_type == "classification":
        return ClassificationInferenceTaskRequest(
            **shared_kwargs,
            top_k=get_optional_int_parameter(request, "top_k") or 5,
        )
    if task_type == "segmentation":
        return SegmentationInferenceTaskRequest(
            **shared_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            mask_threshold=get_optional_float_parameter(request, "mask_threshold") or 0.5,
        )
    if task_type == "pose":
        return PoseInferenceTaskRequest(
            **shared_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            keypoint_confidence_threshold=get_optional_float_parameter(
                request,
                "keypoint_confidence_threshold",
            ),
        )
    if task_type == "obb":
        return ObbInferenceTaskRequest(
            **shared_kwargs,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
        )
    raise ValueError(f"unsupported task_type: {task_type}")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.model-inference.submit",
        display_name="Submit Inference",
        category="service.model.inference",
        description="按 task_type 调用正式 inference API 提交推理任务。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
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
                "task_type": {
                    "type": "string",
                    "enum": ["detection", "classification", "segmentation", "pose", "obb"],
                },
                "project_id": {"type": "string"},
                "deployment_instance_id": {"type": "string"},
                "model_type": {
                    "type": "string",
                    "enum": ["yolox", "yolov8", "yolo11", "yolo26", "rfdetr"],
                },
                "input_file_id": {"type": "string"},
                "input_uri": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "mask_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "keypoint_confidence_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "auto_start_process": {"type": "boolean"},
                "save_result_image": {"type": "boolean"},
                "return_preview_image_base64": {"type": "boolean"},
                "extra_options": {"type": "object"},
                "display_name": {"type": "string"},
                "created_by": {"type": "string"},
            },
            "required": ["project_id", "deployment_instance_id"],
        },
        capability_tags=("service.model.inference", "task.submit"),
        runtime_requirements={"deployment_process": "async"},
    ),
    handler=_model_inference_submit_handler,
)
