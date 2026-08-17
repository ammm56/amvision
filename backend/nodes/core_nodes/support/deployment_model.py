"""已发布 deployment 直连模型节点的共享 helper。"""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    load_image_content,
    require_image_payload,
    resolve_image_reference,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.runtime.policies import (
    should_return_workflow_timing_metadata,
)

if TYPE_CHECKING:
    from backend.service.application.deployments import PublishedInferenceResult


DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD = 0.3
DEFAULT_DIRECT_MODEL_MASK_THRESHOLD = 0.5
DEFAULT_DIRECT_MODEL_TOP_K = 5
DEFAULT_DIRECT_MODEL_KEYPOINT_CONFIDENCE_THRESHOLD = 0.3
DEFAULT_WORKFLOW_LOCAL_BUFFER_TTL_SECONDS = 330.0
WORKFLOW_LOCAL_BUFFER_TTL_GRACE_SECONDS = 30.0
_WORKFLOW_REUSABLE_MODEL_BUFFERS_KEY = "_workflow_reusable_model_buffers"


@dataclass(frozen=True)
class _TemporaryLocalBufferInput:
    """模型同步调用临时写入 LocalBufferBroker 的输入图片。"""

    payload: dict[str, object]
    lease_id: str | None
    pool_name: str | None
    release_after_inference: bool = True


@dataclass(frozen=True)
class _ReusableLocalBufferInput:
    """描述一次 Workflow Run 内可串行复用的模型输入槽位。"""

    lease: object
    buffer_ref_payload: dict[str, object]


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
    image_payload, input_image_bytes, temporary_input = _build_gateway_image_payload(
        request=request,
        resolved_image=resolved_image,
    )
    try:
        inference_result = runtime_context.build_published_inference_gateway().infer(
            PublishedInferenceRequest(
                task_type=task_type,
                deployment_instance_id=require_str_parameter(
                    request, "deployment_instance_id"
                ),
                image_payload=image_payload,
                input_image_bytes=input_image_bytes,
                score_threshold=get_optional_float_parameter(
                    request, "score_threshold"
                ),
                top_k=get_optional_int_parameter(request, "top_k"),
                mask_threshold=get_optional_float_parameter(request, "mask_threshold"),
                keypoint_confidence_threshold=get_optional_float_parameter(
                    request,
                    "keypoint_confidence_threshold",
                ),
                auto_start_process=bool(
                    get_optional_bool_parameter(request, "auto_start_process")
                    is not False
                ),
                runtime_mode="sync",
                save_result_image=bool(
                    get_optional_bool_parameter(request, "save_result_image") is True
                ),
                return_preview_image_base64=bool(
                    get_optional_bool_parameter(request, "return_preview_image_base64")
                    is True
                ),
                extra_options=get_optional_dict_parameter(request, "extra_options"),
                trace_id=_read_optional_trace_id(request),
                execution_scope_id=_read_optional_execution_scope_id(request),
            ),
        )
    finally:
        _release_temporary_local_buffer_input(
            request=request,
            temporary_input=temporary_input,
        )
    if not should_return_workflow_timing_metadata(request.execution_metadata):
        inference_result = _strip_inference_result_diagnostics(inference_result)
    return inference_result, source_image


def _strip_inference_result_diagnostics(
    inference_result: PublishedInferenceResult,
) -> PublishedInferenceResult:
    """移除 workflow 生产调用默认不返回的推理诊断字段。"""

    metadata = dict(inference_result.metadata)
    metadata.pop("timings", None)
    runtime_session_info = _strip_runtime_session_diagnostics(
        inference_result.runtime_session_info
    )
    return replace(
        inference_result,
        metadata=metadata,
        runtime_session_info=runtime_session_info,
    )


def _strip_runtime_session_diagnostics(
    runtime_session_info: dict[str, object],
) -> dict[str, object]:
    """移除 runtime_session_info.metadata 里的耗时诊断字段。"""

    payload = dict(runtime_session_info)
    metadata_value = payload.get("metadata")
    if isinstance(metadata_value, dict):
        metadata = dict(metadata_value)
        for key in tuple(metadata):
            if str(key).endswith("_ms"):
                metadata.pop(key, None)
        payload["metadata"] = metadata
    return payload


def _build_gateway_image_payload(
    *,
    request: WorkflowNodeExecutionRequest,
    resolved_image,
) -> tuple[dict[str, object], bytes | None, _TemporaryLocalBufferInput | None]:
    """构造 PublishedInferenceGateway 使用的图片 payload。"""

    if resolved_image.transport_kind != IMAGE_TRANSPORT_MEMORY:
        return dict(resolved_image.payload), None, None
    normalized_payload, image_bytes = load_image_content(request)
    temporary_input = _try_write_memory_image_to_local_buffer(
        request=request,
        normalized_payload=normalized_payload,
        image_bytes=image_bytes,
    )
    if temporary_input is not None:
        return temporary_input.payload, None, temporary_input
    return (
        dict(normalized_payload),
        image_bytes if isinstance(image_bytes, bytes) else image_bytes.tobytes(),
        None,
    )


def _try_write_memory_image_to_local_buffer(
    *,
    request: WorkflowNodeExecutionRequest,
    normalized_payload: dict[str, object],
    image_bytes: bytes | memoryview,
) -> _TemporaryLocalBufferInput | None:
    """把 execution memory 图片写入 LocalBufferBroker 并返回 BufferRef payload。"""

    local_buffer_writer = request.execution_metadata.get("local_buffer_reader")
    write_bytes = getattr(local_buffer_writer, "write_bytes", None)
    if not callable(write_bytes):
        return None
    reusable_input = _try_reuse_local_buffer_input(
        request=request,
        local_buffer_writer=local_buffer_writer,
        normalized_payload=normalized_payload,
        image_bytes=image_bytes,
    )
    if reusable_input is not None:
        return reusable_input
    write_result = write_bytes(
        content=image_bytes,
        owner_kind="workflow-runtime",
        owner_id=_build_buffer_owner_id(request),
        media_type=str(normalized_payload["media_type"]),
        shape=tuple(
            int(item)
            for item in require_image_payload(normalized_payload).get("shape", ())
        ),
        dtype=_read_optional_payload_text(normalized_payload, "dtype"),
        layout=_read_optional_payload_text(normalized_payload, "layout"),
        pixel_format=_read_optional_payload_text(normalized_payload, "pixel_format"),
        trace_id=_read_optional_trace_id(request),
        ttl_seconds=_resolve_workflow_local_buffer_ttl_seconds(request),
    )
    buffer_payload = dict(normalized_payload)
    buffer_payload["transport_kind"] = IMAGE_TRANSPORT_BUFFER
    buffer_payload["buffer_ref"] = write_result.buffer_ref.model_dump(mode="json")
    buffer_payload.pop("image_handle", None)
    buffer_payload.pop("object_key", None)
    buffer_payload.pop("frame_ref", None)
    lease = getattr(write_result, "lease", None)
    lease_id = getattr(lease, "lease_id", None)
    pool_name = getattr(lease, "pool_name", None)
    temporary_input = _TemporaryLocalBufferInput(
        payload=buffer_payload,
        lease_id=lease_id.strip()
        if isinstance(lease_id, str) and lease_id.strip()
        else None,
        pool_name=pool_name.strip()
        if isinstance(pool_name, str) and pool_name.strip()
        else None,
        release_after_inference=not _supports_reusable_model_buffer(request),
    )
    if not temporary_input.release_after_inference and temporary_input.lease_id is not None:
        _register_local_buffer_lease_cleanup(
            request=request,
            lease_id=temporary_input.lease_id,
            pool_name=temporary_input.pool_name,
        )
        _remember_reusable_local_buffer_input(
            request=request,
            normalized_payload=normalized_payload,
            image_bytes=image_bytes,
            lease=write_result.lease,
            buffer_ref_payload=write_result.buffer_ref.model_dump(mode="json"),
        )
    return temporary_input


def _release_temporary_local_buffer_input(
    *,
    request: WorkflowNodeExecutionRequest,
    temporary_input: _TemporaryLocalBufferInput | None,
) -> None:
    """同步模型调用完成后立即释放临时 LocalBufferBroker 输入图片。"""

    if (
        temporary_input is None
        or temporary_input.lease_id is None
        or not temporary_input.release_after_inference
    ):
        return
    local_buffer_writer = request.execution_metadata.get("local_buffer_reader")
    release = getattr(local_buffer_writer, "release", None)
    if not callable(release):
        _register_local_buffer_lease_cleanup(
            request=request,
            lease_id=temporary_input.lease_id,
            pool_name=temporary_input.pool_name,
        )
        return
    try:
        release(temporary_input.lease_id, pool_name=temporary_input.pool_name)
    except Exception:
        _register_local_buffer_lease_cleanup(
            request=request,
            lease_id=temporary_input.lease_id,
            pool_name=temporary_input.pool_name,
        )


def _register_local_buffer_lease_cleanup(
    *,
    request: WorkflowNodeExecutionRequest,
    lease_id: str,
    pool_name: str | None,
) -> None:
    """登记当前节点写入的 LocalBufferBroker lease 清理项。"""

    from backend.service.application.workflows.execution_cleanup import (
        register_local_buffer_lease_cleanup,
    )

    if not isinstance(lease_id, str) or not lease_id.strip():
        return
    register_local_buffer_lease_cleanup(
        request.execution_metadata,
        lease_id=lease_id.strip(),
        pool_name=pool_name.strip()
        if isinstance(pool_name, str) and pool_name.strip()
        else None,
    )


def _supports_reusable_model_buffer(request: WorkflowNodeExecutionRequest) -> bool:
    """判断当前调用是否处于具备统一 cleanup 的 Workflow Run。"""

    from backend.service.application.workflows.execution_cleanup import (
        WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY,
    )

    local_buffer_writer = request.execution_metadata.get("local_buffer_reader")
    return (
        isinstance(
            request.execution_metadata.get(WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY),
            list,
        )
        and callable(getattr(local_buffer_writer, "write_lease_bytes", None))
    )


def _try_reuse_local_buffer_input(
    *,
    request: WorkflowNodeExecutionRequest,
    local_buffer_writer: object,
    normalized_payload: dict[str, object],
    image_bytes: bytes | memoryview,
) -> _TemporaryLocalBufferInput | None:
    """在同一循环节点的串行推理间复用已经提交的 mmap 槽位。"""

    if not _supports_reusable_model_buffer(request):
        return None
    cache = request.execution_metadata.get(_WORKFLOW_REUSABLE_MODEL_BUFFERS_KEY)
    if not isinstance(cache, dict):
        return None
    cache_key = _build_reusable_model_buffer_key(
        request=request,
        normalized_payload=normalized_payload,
        image_bytes=image_bytes,
    )
    cached = cache.get(cache_key)
    if not isinstance(cached, _ReusableLocalBufferInput):
        return None
    write_lease_bytes = getattr(local_buffer_writer, "write_lease_bytes", None)
    if not callable(write_lease_bytes):
        return None
    write_lease_bytes(lease=cached.lease, content=image_bytes)
    buffer_payload = dict(normalized_payload)
    buffer_payload["transport_kind"] = IMAGE_TRANSPORT_BUFFER
    buffer_payload["buffer_ref"] = dict(cached.buffer_ref_payload)
    buffer_payload.pop("image_handle", None)
    buffer_payload.pop("object_key", None)
    buffer_payload.pop("frame_ref", None)
    lease_id = cached.buffer_ref_payload.get("lease_id")
    return _TemporaryLocalBufferInput(
        payload=buffer_payload,
        lease_id=lease_id if isinstance(lease_id, str) else None,
        pool_name=None,
        release_after_inference=False,
    )


def _remember_reusable_local_buffer_input(
    *,
    request: WorkflowNodeExecutionRequest,
    normalized_payload: dict[str, object],
    image_bytes: bytes | memoryview,
    lease: object,
    buffer_ref_payload: dict[str, object],
) -> None:
    """保存本次循环节点后续调用可直接覆盖的 mmap 槽位。"""

    raw_cache = request.execution_metadata.get(_WORKFLOW_REUSABLE_MODEL_BUFFERS_KEY)
    if not isinstance(raw_cache, dict):
        raw_cache = {}
        request.execution_metadata[_WORKFLOW_REUSABLE_MODEL_BUFFERS_KEY] = raw_cache
    raw_cache[
        _build_reusable_model_buffer_key(
            request=request,
            normalized_payload=normalized_payload,
            image_bytes=image_bytes,
        )
    ] = _ReusableLocalBufferInput(
        lease=lease,
        buffer_ref_payload=dict(buffer_ref_payload),
    )


def _build_reusable_model_buffer_key(
    *,
    request: WorkflowNodeExecutionRequest,
    normalized_payload: dict[str, object],
    image_bytes: bytes | memoryview,
) -> tuple[object, ...]:
    """构造仅在图片存储布局完全一致时命中的槽位复用键。"""

    image_payload = require_image_payload(normalized_payload)
    return (
        request.node_id,
        len(image_bytes),
        str(normalized_payload.get("media_type") or ""),
        tuple(image_payload.get("shape", ())),
        _read_optional_payload_text(normalized_payload, "dtype"),
        _read_optional_payload_text(normalized_payload, "layout"),
        _read_optional_payload_text(normalized_payload, "pixel_format"),
    )


def _build_buffer_owner_id(request: WorkflowNodeExecutionRequest) -> str:
    """构造写入 LocalBufferBroker 时使用的 owner_id。"""

    workflow_run_id = request.execution_metadata.get("workflow_run_id")
    if isinstance(workflow_run_id, str) and workflow_run_id.strip():
        return f"{workflow_run_id.strip()}:{request.node_id}"
    return request.node_id


def _resolve_workflow_local_buffer_ttl_seconds(
    request: WorkflowNodeExecutionRequest,
) -> float:
    """解析临时模型输入 lease 的正数 TTL，并覆盖完整 Workflow Run 超时。"""

    from backend.service.application.workflows.execution_cleanup import (
        WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY,
    )

    raw_timeout = request.execution_metadata.get(
        WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY
    )
    if isinstance(raw_timeout, bool):
        return DEFAULT_WORKFLOW_LOCAL_BUFFER_TTL_SECONDS
    if isinstance(raw_timeout, (int, float)) and float(raw_timeout) > 0:
        return float(raw_timeout) + WORKFLOW_LOCAL_BUFFER_TTL_GRACE_SECONDS
    return DEFAULT_WORKFLOW_LOCAL_BUFFER_TTL_SECONDS


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


def _read_optional_execution_scope_id(
    request: WorkflowNodeExecutionRequest,
) -> str | None:
    """读取稳定运行时作用域 id，供连续 Workflow Run 复用 deployment 上下文。"""

    from backend.service.application.workflows.model_sessions import (
        WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY,
    )

    model_session_scope_id = request.execution_metadata.get(
        WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY
    )
    if isinstance(model_session_scope_id, str) and model_session_scope_id.strip():
        return model_session_scope_id.strip()

    workflow_run_id = request.execution_metadata.get("workflow_run_id")
    if isinstance(workflow_run_id, str) and workflow_run_id.strip():
        return workflow_run_id.strip()
    return None
