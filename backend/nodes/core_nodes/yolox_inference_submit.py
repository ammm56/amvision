"""YOLOX inference task service node。"""

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
    ensure_running_deployment_process,
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_float_parameter,
    get_optional_image_object_key,
    get_optional_str_parameter,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
    resolve_display_name,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_inference_task_service import (
    YoloXInferenceTaskRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _yolox_inference_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用现有 YOLOX inference task 提交服务。"""

    runtime_context = require_workflow_service_node_runtime(request)
    deployment_service = runtime_context.build_deployment_service()
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
    deployment_process_supervisor = runtime_context.require_async_deployment_process_supervisor()
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

    submission = runtime_context.build_inference_task_service().submit_inference_task(
        YoloXInferenceTaskRequest(
            project_id=project_id,
            deployment_instance_id=deployment_instance_id,
            input_file_id=input_file_id,
            input_uri=normalized_input_uri,
            input_source_kind=input_source_kind,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            save_result_image=get_optional_bool_parameter(request, "save_result_image")
            if get_optional_bool_parameter(request, "save_result_image") is not None
            else False,
            return_preview_image_base64=get_optional_bool_parameter(request, "return_preview_image_base64")
            if get_optional_bool_parameter(request, "return_preview_image_base64") is not None
            else False,
            extra_options=get_optional_dict_parameter(request, "extra_options"),
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


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-inference.submit",
        display_name="Submit YOLOX Inference",
        category="service.model.inference",
        description="按现有 inference task API 的公开参数直接提交一个正式推理任务。",
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
                "project_id": {"type": "string"},
                "deployment_instance_id": {"type": "string"},
                "input_file_id": {"type": "string"},
                "input_uri": {"type": "string"},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
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
    handler=_yolox_inference_submit_handler,
)