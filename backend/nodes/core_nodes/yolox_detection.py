"""YOLOX 检测节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._service_node_support import (
    ensure_running_deployment_process,
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_float_parameter,
    require_str_parameter,
    require_workflow_service_node_runtime,
)
from backend.nodes.runtime_support import resolve_image_input
from backend.service.application.models.yolox_inference_task_service import run_yolox_inference_task
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


_DEFAULT_INFERENCE_SCORE_THRESHOLD = 0.3


def _yolox_detection_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用现有同步 YOLOX 推理链并输出 detections。"""

    runtime_context = require_workflow_service_node_runtime(request)
    deployment_service = runtime_context.build_deployment_service()
    deployment_instance_id = require_str_parameter(request, "deployment_instance_id")
    process_config = deployment_service.resolve_process_config(deployment_instance_id)
    deployment_process_supervisor = runtime_context.require_sync_deployment_process_supervisor()
    deployment_process_supervisor.ensure_deployment(process_config)
    auto_start_process = get_optional_bool_parameter(request, "auto_start_process")
    ensure_running_deployment_process(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        runtime_mode="sync",
        auto_start_process=True if auto_start_process is None else auto_start_process,
    )
    _, _, object_key = resolve_image_input(request)
    execution_result = run_yolox_inference_task(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        input_uri=object_key,
        score_threshold=get_optional_float_parameter(request, "score_threshold")
        or _DEFAULT_INFERENCE_SCORE_THRESHOLD,
        save_result_image=get_optional_bool_parameter(request, "save_result_image")
        if get_optional_bool_parameter(request, "save_result_image") is not None
        else False,
        return_preview_image_base64=get_optional_bool_parameter(request, "return_preview_image_base64")
        if get_optional_bool_parameter(request, "return_preview_image_base64") is not None
        else False,
        extra_options=get_optional_dict_parameter(request, "extra_options"),
    )
    return {"detections": {"items": list(execution_result.detections)}}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.model.yolox-detection",
        display_name="YOLOX Detection",
        category="model.inference",
        description="调用独立推理 worker 产出标准 detection 结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_WORKER_TASK,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "deployment_instance_id": {"type": "string"},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "auto_start_process": {"type": "boolean"},
                "save_result_image": {"type": "boolean"},
                "return_preview_image_base64": {"type": "boolean"},
                "extra_options": {"type": "object"},
            },
            "required": ["deployment_instance_id"],
        },
        capability_tags=("model.inference", "yolox.detection"),
        runtime_requirements={"deployment_process": "sync"},
    ),
    handler=_yolox_detection_handler,
)