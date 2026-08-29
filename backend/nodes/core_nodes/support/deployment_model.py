"""已发布 deployment 直连模型节点的共享 helper。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
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
    IMAGE_TRANSPORT_LOCAL_PATH,
    IMAGE_TRANSPORT_MEMORY,
    load_image_content,
    load_image_content_from_payload,
    require_image_payload,
    resolve_image_reference,
)
from backend.nodes.core_nodes.support.typed_payload_bridges import (
    require_image_refs_payload,
)
from backend.nodes.core_nodes.support.deployment_result_payloads import (
    build_deployment_result_payload,
)
from backend.service.application.errors import ServiceError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.runtime.policies import (
    should_return_workflow_timing_metadata,
)

if TYPE_CHECKING:
    from backend.service.application.deployments import (
        PublishedInferenceBatchResult,
        PublishedInferenceResult,
    )


DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD = 0.3
DEFAULT_DIRECT_MODEL_MASK_THRESHOLD = 0.5
DEFAULT_DIRECT_MODEL_TOP_K = 5
DEFAULT_DIRECT_MODEL_KEYPOINT_CONFIDENCE_THRESHOLD = 0.3
DEFAULT_WORKFLOW_LOCAL_BUFFER_TTL_SECONDS = 330.0
WORKFLOW_LOCAL_BUFFER_TTL_GRACE_SECONDS = 30.0


@dataclass(frozen=True)
class _TemporaryLocalBufferInput:
    """模型同步调用临时写入 LocalBufferBroker 的输入图片。"""

    payload: dict[str, object]
    lease_id: str | None
    release_after_inference: bool = True


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


def run_direct_model_batch_inference(
    request: WorkflowNodeExecutionRequest,
    *,
    task_type: str,
    format_id: str,
    result_payload_type_id: str,
) -> dict[str, object]:
    """调用 gateway 执行一次有序 Batch，并构造统一结果信封。"""

    from backend.service.application.deployments import (
        PublishedInferenceBatchRequest,
        PublishedInferenceRequest,
    )
    from backend.service.application.runtime.deployment.deployment_runtime_pool import (
        MAX_DEPLOYMENT_RUNTIME_BATCH_ITEMS,
    )

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    images_payload = require_image_refs_payload(
        request.input_values.get("images"),
        request.node_id,
    )
    source_images = [dict(item) for item in images_payload["items"]]
    if not source_images:
        from backend.service.application.errors import InvalidRequestError

        raise InvalidRequestError(
            "模型 Batch 节点至少需要 1 张图片",
            details={"node_id": request.node_id},
        )
    if len(source_images) > MAX_DEPLOYMENT_RUNTIME_BATCH_ITEMS:
        from backend.service.application.errors import InvalidRequestError

        raise InvalidRequestError(
            "模型 Batch 节点图片数量超过上限",
            details={
                "node_id": request.node_id,
                "count": len(source_images),
                "max_count": MAX_DEPLOYMENT_RUNTIME_BATCH_ITEMS,
            },
        )

    temporary_inputs: list[_TemporaryLocalBufferInput] = []
    published_requests: list[PublishedInferenceRequest] = []
    input_stage_started_at = perf_counter()
    input_stage_ms = 0.0
    gateway_ms = 0.0
    release_ms = 0.0
    try:
        gateway_inputs = _build_gateway_image_payloads_from_sources(
            request=request,
            source_images=source_images,
        )
        input_stage_ms = (perf_counter() - input_stage_started_at) * 1000.0
        for source_image, (
            image_payload,
            input_image_bytes,
            temporary_input,
        ) in zip(source_images, gateway_inputs, strict=True):
            if temporary_input is not None:
                temporary_inputs.append(temporary_input)
            published_requests.append(
                _build_published_inference_request(
                    request=request,
                    task_type=task_type,
                    image_payload=image_payload,
                    input_image_bytes=input_image_bytes,
                    allow_preview=False,
                )
            )
        try:
            gateway_started_at = perf_counter()
            inference_batch = (
                runtime_context.build_published_inference_gateway().infer_batch(
                    PublishedInferenceBatchRequest(
                        requests=tuple(published_requests),
                    )
                )
            )
            gateway_ms = (perf_counter() - gateway_started_at) * 1000.0
        except ServiceError as error:
            _attach_batch_item_error_context(
                error=error,
                source_images=source_images,
            )
            raise
    finally:
        release_started_at = perf_counter()
        _release_temporary_local_buffer_inputs(
            request=request,
            temporary_inputs=temporary_inputs,
        )
        release_ms = (perf_counter() - release_started_at) * 1000.0

    if not should_return_workflow_timing_metadata(request.execution_metadata):
        inference_batch = _strip_batch_inference_diagnostics(inference_batch)
    if len(inference_batch.results) != len(source_images):
        from backend.service.application.errors import ServiceConfigurationError

        raise ServiceConfigurationError(
            "模型 Batch 返回数量与输入数量不一致",
            details={
                "node_id": request.node_id,
                "input_count": len(source_images),
                "result_count": len(inference_batch.results),
            },
        )

    result_build_started_at = perf_counter()
    items = []
    for item_index, (source_image, inference_result) in enumerate(
        zip(source_images, inference_batch.results, strict=True)
    ):
        items.append(
            {
                "item_index": item_index,
                "item_id": _build_batch_item_id(source_image, item_index),
                "source": _build_locator_free_batch_source(source_image),
                "result": build_deployment_result_payload(
                    task_type=task_type,
                    inference_result=inference_result,
                    source_image=None,
                ),
            }
        )
    result_build_ms = (perf_counter() - result_build_started_at) * 1000.0
    metadata = {
        **dict(inference_batch.metadata),
        "deployment_instance_id": inference_batch.deployment_instance_id,
        "instance_id": inference_batch.instance_id,
        "execution_mode": "sequential-reserved-instance",
    }
    if should_return_workflow_timing_metadata(request.execution_metadata):
        metadata["workflow_batch_timings"] = {
            "input_stage_ms": round(input_stage_ms, 3),
            "gateway_ms": round(gateway_ms, 3),
            "release_ms": round(release_ms, 3),
            "result_build_ms": round(result_build_ms, 3),
        }
    return {
        "format_id": format_id,
        "task_type": task_type,
        "result_payload_type_id": result_payload_type_id,
        "count": len(items),
        "items": items,
        "batch_latency_ms": inference_batch.batch_latency_ms,
        "metadata": metadata,
    }


def _build_published_inference_request(
    *,
    request: WorkflowNodeExecutionRequest,
    task_type: str,
    image_payload: dict[str, object],
    input_image_bytes: bytes | None,
    allow_preview: bool,
):
    """使用节点公共参数构造单项 PublishedInferenceRequest。"""

    from backend.service.application.deployments import PublishedInferenceRequest

    return PublishedInferenceRequest(
        task_type=task_type,
        deployment_instance_id=require_str_parameter(
            request,
            "deployment_instance_id",
        ),
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
        save_result_image=(
            allow_preview
            and get_optional_bool_parameter(request, "save_result_image") is True
        ),
        return_preview_image_base64=(
            allow_preview
            and get_optional_bool_parameter(request, "return_preview_image_base64")
            is True
        ),
        extra_options=get_optional_dict_parameter(request, "extra_options"),
        trace_id=_read_optional_trace_id(request),
        execution_scope_id=_read_optional_execution_scope_id(request),
    )


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


def _strip_batch_inference_diagnostics(
    inference_batch: PublishedInferenceBatchResult,
) -> PublishedInferenceBatchResult:
    """移除 Batch 及每项结果中默认关闭的耗时诊断。"""

    metadata = dict(inference_batch.metadata)
    metadata.pop("timings", None)
    return replace(
        inference_batch,
        results=tuple(
            _strip_inference_result_diagnostics(result)
            for result in inference_batch.results
        ),
        metadata=metadata,
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

    if resolved_image.transport_kind not in {
        IMAGE_TRANSPORT_MEMORY,
        IMAGE_TRANSPORT_LOCAL_PATH,
    }:
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


def _build_gateway_image_payload_from_source(
    *,
    request: WorkflowNodeExecutionRequest,
    source_image: dict[str, object],
) -> tuple[dict[str, object], bytes | None, _TemporaryLocalBufferInput | None]:
    """构造 Batch 单项的 gateway 图片输入，不依赖固定 ``image`` 端口。"""

    normalized_source = require_image_payload(source_image)
    if normalized_source.get("transport_kind") not in {
        IMAGE_TRANSPORT_MEMORY,
        IMAGE_TRANSPORT_LOCAL_PATH,
    }:
        return normalized_source, None, None
    normalized_payload, image_bytes = load_image_content_from_payload(
        request,
        image_payload=normalized_source,
    )
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


def _build_gateway_image_payloads_from_sources(
    *,
    request: WorkflowNodeExecutionRequest,
    source_images: list[dict[str, object]],
) -> list[
    tuple[dict[str, object], bytes | None, _TemporaryLocalBufferInput | None]
]:
    """优先用 LocalBuffer 批量控制消息准备同一 Batch 的全部图片。"""

    local_buffer_writer = request.execution_metadata.get("local_buffer_reader")
    write_many = getattr(local_buffer_writer, "write_many", None)
    if not callable(write_many):
        return [
            _build_gateway_image_payload_from_source(
                request=request,
                source_image=source_image,
            )
            for source_image in source_images
        ]

    normalized_items: list[tuple[dict[str, object], bytes | memoryview]] = []
    for source_image in source_images:
        normalized_source = require_image_payload(source_image)
        if normalized_source.get("transport_kind") not in {
            IMAGE_TRANSPORT_MEMORY,
            IMAGE_TRANSPORT_LOCAL_PATH,
        }:
            return [
                _build_gateway_image_payload_from_source(
                    request=request,
                    source_image=current_source,
                )
                for current_source in source_images
            ]
        normalized_payload, image_bytes = load_image_content_from_payload(
            request,
            image_payload=normalized_source,
        )
        normalized_items.append((normalized_payload, image_bytes))

    write_results = write_many(
        items=tuple(
            {
                "content": image_bytes,
                "media_type": str(normalized_payload["media_type"]),
                "shape": tuple(
                    int(item)
                    for item in require_image_payload(normalized_payload).get(
                        "shape",
                        (),
                    )
                ),
                "dtype": _read_optional_payload_text(normalized_payload, "dtype"),
                "layout": _read_optional_payload_text(normalized_payload, "layout"),
                "pixel_format": _read_optional_payload_text(
                    normalized_payload,
                    "pixel_format",
                ),
            }
            for normalized_payload, image_bytes in normalized_items
        ),
        owner_kind="workflow-runtime",
        owner_id=_build_buffer_owner_id(request),
        trace_id=_read_optional_trace_id(request),
        ttl_seconds=_resolve_workflow_local_buffer_ttl_seconds(request),
    )
    if not isinstance(write_results, tuple) or len(write_results) != len(
        normalized_items
    ):
        from backend.service.application.errors import ServiceConfigurationError

        raise ServiceConfigurationError("LocalBuffer 批量写入返回数量不一致")
    prepared: list[
        tuple[dict[str, object], bytes | None, _TemporaryLocalBufferInput | None]
    ] = []
    for (normalized_payload, _image_bytes), write_result in zip(
        normalized_items,
        write_results,
        strict=True,
    ):
        temporary_input = _build_temporary_local_buffer_input(
            normalized_payload=normalized_payload,
            write_result=write_result,
        )
        prepared.append((temporary_input.payload, None, temporary_input))
    return prepared


_BATCH_SOURCE_FIELDS = frozenset(
    {
        "item_id",
        "id",
        "crop_id",
        "crop_index",
        "roi_id",
        "region_id",
        "source_index",
        "frame_index",
        "timestamp_ms",
        "bbox_xyxy",
        "width",
        "height",
        "shape",
        "dtype",
        "layout",
        "pixel_format",
        "media_type",
        "content_sha256",
        "label",
        "name",
    }
)


def _build_locator_free_batch_source(
    source_image: dict[str, object],
) -> dict[str, object]:
    """只保留 Batch JSON 可公开的非 locator 图片关联字段。"""

    return {
        key: value
        for key, value in source_image.items()
        if key in _BATCH_SOURCE_FIELDS
    }


def _build_batch_item_id(
    source_image: dict[str, object],
    item_index: int,
) -> str:
    """按显式 id、crop_index 和稳定回退值构造 Batch item_id。"""

    for key in ("item_id", "id", "crop_id", "roi_id", "region_id"):
        value = source_image.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    crop_index = source_image.get("crop_index")
    if isinstance(crop_index, int) and not isinstance(crop_index, bool):
        return f"crop-{crop_index}"
    return f"item-{item_index}"


def _attach_batch_item_error_context(
    *,
    error: ServiceError,
    source_images: list[dict[str, object]],
) -> None:
    """把 gateway 的 item_index 补充为可定位的 Batch item_id。"""

    item_index = error.details.get("item_index")
    if (
        isinstance(item_index, bool)
        or not isinstance(item_index, int)
        or item_index < 0
        or item_index >= len(source_images)
    ):
        return
    error.details.setdefault(
        "item_id",
        _build_batch_item_id(source_images[item_index], item_index),
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
    return _build_temporary_local_buffer_input(
        normalized_payload=normalized_payload,
        write_result=write_result,
    )


def _build_temporary_local_buffer_input(
    *,
    normalized_payload: dict[str, object],
    write_result: object,
) -> _TemporaryLocalBufferInput:
    """把单项或批量 LocalBuffer 写入结果转换为临时图片引用。"""

    buffer_ref = getattr(write_result, "buffer_ref", None)
    model_dump = getattr(buffer_ref, "model_dump", None)
    if not callable(model_dump):
        from backend.service.application.errors import ServiceConfigurationError

        raise ServiceConfigurationError("LocalBuffer 写入结果缺少 buffer_ref")
    buffer_payload = dict(normalized_payload)
    buffer_payload["transport_kind"] = IMAGE_TRANSPORT_BUFFER
    buffer_payload["buffer_ref"] = model_dump(mode="json")
    buffer_payload.pop("image_handle", None)
    buffer_payload.pop("object_key", None)
    buffer_payload.pop("local_path", None)
    buffer_payload.pop("frame_ref", None)
    lease = getattr(write_result, "lease", None)
    lease_id = getattr(lease, "lease_id", None)
    temporary_input = _TemporaryLocalBufferInput(
        payload=buffer_payload,
        lease_id=lease_id.strip()
        if isinstance(lease_id, str) and lease_id.strip()
        else None,
        release_after_inference=True,
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
        )
        return
    try:
        release(temporary_input.lease_id)
    except Exception:
        _register_local_buffer_lease_cleanup(
            request=request,
            lease_id=temporary_input.lease_id,
        )


def _release_temporary_local_buffer_inputs(
    *,
    request: WorkflowNodeExecutionRequest,
    temporary_inputs: list[_TemporaryLocalBufferInput],
) -> None:
    """按当前 Batch 节点 owner 一次释放全部临时输入 lease。"""

    owned_inputs = [
        item
        for item in temporary_inputs
        if item.release_after_inference and item.lease_id is not None
    ]
    if not owned_inputs:
        return
    local_buffer_writer = request.execution_metadata.get("local_buffer_reader")
    release_owner = getattr(local_buffer_writer, "release_owner", None)
    if callable(release_owner):
        try:
            release_owner(
                owner_kind="workflow-runtime",
                owner_id=_build_buffer_owner_id(request),
            )
            return
        except Exception:
            pass
    for temporary_input in owned_inputs:
        _release_temporary_local_buffer_input(
            request=request,
            temporary_input=temporary_input,
        )


def _register_local_buffer_lease_cleanup(
    *,
    request: WorkflowNodeExecutionRequest,
    lease_id: str,
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
