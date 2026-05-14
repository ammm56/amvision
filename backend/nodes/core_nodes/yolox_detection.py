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
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_float_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
)
from backend.nodes.runtime_support import IMAGE_TRANSPORT_BUFFER, IMAGE_TRANSPORT_MEMORY, load_image_bytes, resolve_image_reference
from backend.service.application.deployments import PublishedInferenceRequest
from backend.service.application.workflows.execution_cleanup import register_local_buffer_lease_cleanup
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


_DEFAULT_INFERENCE_SCORE_THRESHOLD = 0.3


def _yolox_detection_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """通过 PublishedInferenceGateway 调用已发布 YOLOX 推理服务。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    deployment_instance_id = require_str_parameter(request, "deployment_instance_id")
    auto_start_process = get_optional_bool_parameter(request, "auto_start_process")
    save_result_image = get_optional_bool_parameter(request, "save_result_image")
    return_preview_image_base64 = get_optional_bool_parameter(request, "return_preview_image_base64")
    image_payload, input_image_bytes = _build_gateway_image_payload(request)
    inference_result = runtime_context.build_published_inference_gateway().infer(
        PublishedInferenceRequest(
            deployment_instance_id=deployment_instance_id,
            image_payload=image_payload,
            input_image_bytes=input_image_bytes,
            auto_start_process=True if auto_start_process is None else auto_start_process,
            runtime_mode="sync",
            score_threshold=get_optional_float_parameter(request, "score_threshold")
            or _DEFAULT_INFERENCE_SCORE_THRESHOLD,
            save_result_image=False if save_result_image is None else save_result_image,
            return_preview_image_base64=False
            if return_preview_image_base64 is None
            else return_preview_image_base64,
            extra_options=get_optional_dict_parameter(request, "extra_options"),
            trace_id=_read_optional_trace_id(request),
        )
    )
    return {"detections": {"items": list(inference_result.detections)}}


def _build_gateway_image_payload(request: WorkflowNodeExecutionRequest) -> tuple[dict[str, object], bytes | None]:
    """构造 PublishedInferenceGateway 使用的图片 payload。

    参数：
    - request：当前节点执行请求。

    返回：
    - tuple[dict[str, object], bytes | None]：可跨进程传递的 image-ref payload 与可选图片字节。
    """

    resolved_image = resolve_image_reference(request)
    if resolved_image.transport_kind != IMAGE_TRANSPORT_MEMORY:
        return dict(resolved_image.payload), None
    normalized_payload, image_bytes = load_image_bytes(request)
    buffer_payload = _try_write_memory_image_to_local_buffer(
        request=request,
        normalized_payload=normalized_payload,
        image_bytes=image_bytes,
    )
    if buffer_payload is not None:
        return buffer_payload, None
    return dict(normalized_payload), image_bytes


def _try_write_memory_image_to_local_buffer(
    *,
    request: WorkflowNodeExecutionRequest,
    normalized_payload: dict[str, object],
    image_bytes: bytes,
) -> dict[str, object] | None:
    """把 execution memory 图片写入 LocalBufferBroker 并返回 BufferRef payload。"""

    local_buffer_writer = request.execution_metadata.get("local_buffer_reader")
    write_bytes = getattr(local_buffer_writer, "write_bytes", None)
    if not callable(write_bytes):
        return None
    write_result = write_bytes(
        content=image_bytes,
        owner_kind="workflow-runtime",
        owner_id=_build_buffer_owner_id(request),
        media_type=str(normalized_payload["media_type"]),
        trace_id=_read_optional_trace_id(request),
    )
    _register_local_buffer_lease_cleanup(request=request, write_result=write_result)
    buffer_payload = dict(normalized_payload)
    buffer_payload["transport_kind"] = IMAGE_TRANSPORT_BUFFER
    buffer_payload["buffer_ref"] = write_result.buffer_ref.model_dump(mode="json")
    buffer_payload.pop("image_handle", None)
    buffer_payload.pop("object_key", None)
    buffer_payload.pop("frame_ref", None)
    return buffer_payload


def _register_local_buffer_lease_cleanup(
    *,
    request: WorkflowNodeExecutionRequest,
    write_result: object,
) -> None:
    """登记当前节点写入的 LocalBufferBroker lease 清理项。"""

    lease = getattr(write_result, "lease", None)
    lease_id = getattr(lease, "lease_id", None)
    if not isinstance(lease_id, str) or not lease_id.strip():
        return
    pool_name = getattr(lease, "pool_name", None)
    register_local_buffer_lease_cleanup(
        request.execution_metadata,
        lease_id=lease_id,
        pool_name=pool_name if isinstance(pool_name, str) else None,
    )


def _build_buffer_owner_id(request: WorkflowNodeExecutionRequest) -> str:
    """构造写入 LocalBufferBroker 时使用的 owner_id。"""

    workflow_run_id = request.execution_metadata.get("workflow_run_id")
    if isinstance(workflow_run_id, str) and workflow_run_id.strip():
        return f"{workflow_run_id.strip()}:{request.node_id}"
    return request.node_id


def _read_optional_trace_id(request: WorkflowNodeExecutionRequest) -> str | None:
    """从执行元数据中读取可选 trace_id。"""

    trace_id = request.execution_metadata.get("trace_id")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    workflow_run_id = request.execution_metadata.get("workflow_run_id")
    if isinstance(workflow_run_id, str) and workflow_run_id.strip():
        return workflow_run_id.strip()
    return None


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
            NodePortDefinition(
                name="dependency",
                display_name="Dependency",
                payload_type_id="response-body.v1",
                required=False,
            ),
            NodePortDefinition(
                name="request",
                display_name="Request",
                payload_type_id="value.v1",
                required=False,
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