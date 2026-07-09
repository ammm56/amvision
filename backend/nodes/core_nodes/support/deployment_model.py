"""已发布 deployment 直连模型节点的共享 helper。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.nodes.core_nodes.support.service import (
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_float_parameter,
    get_optional_int_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
)
from backend.nodes.runtime_support import (
    IMAGE_TRANSPORT_BUFFER,
    IMAGE_TRANSPORT_MEMORY,
    load_image_bytes,
    require_image_payload,
    resolve_image_reference,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest

if TYPE_CHECKING:
    from backend.service.application.deployments import PublishedInferenceResult


DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD = 0.3
DEFAULT_DIRECT_MODEL_MASK_THRESHOLD = 0.5
DEFAULT_DIRECT_MODEL_TOP_K = 5
DEFAULT_DIRECT_MODEL_KEYPOINT_CONFIDENCE_THRESHOLD = 0.3


def run_direct_model_inference(
    request: WorkflowNodeExecutionRequest,
    *,
    task_type: str,
) -> tuple[PublishedInferenceResult, dict[str, object]]:
    """调用 PublishedInferenceGateway 执行 task-native 已发布模型推理。"""

    from backend.service.application.deployments import PublishedInferenceRequest

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    resolved_image = resolve_image_reference(request)
    source_image = dict(resolved_image.payload)
    image_payload, input_image_bytes = _build_gateway_image_payload(
        request=request,
        resolved_image=resolved_image,
    )
    inference_result = runtime_context.build_published_inference_gateway().infer(
        PublishedInferenceRequest(
            task_type=task_type,
            deployment_instance_id=require_str_parameter(request, "deployment_instance_id"),
            image_payload=image_payload,
            input_image_bytes=input_image_bytes,
            score_threshold=get_optional_float_parameter(request, "score_threshold"),
            top_k=get_optional_int_parameter(request, "top_k"),
            mask_threshold=get_optional_float_parameter(request, "mask_threshold"),
            keypoint_confidence_threshold=get_optional_float_parameter(
                request,
                "keypoint_confidence_threshold",
            ),
            auto_start_process=bool(
                get_optional_bool_parameter(request, "auto_start_process") is not False
            ),
            runtime_mode="sync",
            save_result_image=bool(get_optional_bool_parameter(request, "save_result_image") is True),
            return_preview_image_base64=bool(
                get_optional_bool_parameter(request, "return_preview_image_base64") is True
            ),
            extra_options=get_optional_dict_parameter(request, "extra_options"),
            trace_id=_read_optional_trace_id(request),
        )
    )
    return inference_result, source_image


def _build_gateway_image_payload(
    *,
    request: WorkflowNodeExecutionRequest,
    resolved_image,
) -> tuple[dict[str, object], bytes | None]:
    """构造 PublishedInferenceGateway 使用的图片 payload。"""

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
        shape=tuple(int(item) for item in require_image_payload(normalized_payload).get("shape", ())),
        dtype=_read_optional_payload_text(normalized_payload, "dtype"),
        layout=_read_optional_payload_text(normalized_payload, "layout"),
        pixel_format=_read_optional_payload_text(normalized_payload, "pixel_format"),
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

    from backend.service.application.workflows.execution_cleanup import (
        register_local_buffer_lease_cleanup,
    )

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


def _read_optional_payload_text(payload: dict[str, object], key: str) -> str | None:
    """从图片 payload 中读取可选字符串字段。"""

    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _read_optional_trace_id(request: WorkflowNodeExecutionRequest) -> str | None:
    """从执行元数据中读取可选 trace_id。"""

    trace_id = request.execution_metadata.get("trace_id")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    workflow_run_id = request.execution_metadata.get("workflow_run_id")
    if isinstance(workflow_run_id, str) and workflow_run_id.strip():
        return workflow_run_id.strip()
    return None
