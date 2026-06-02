"""帧窗口预览节点。"""

from __future__ import annotations

import mimetypes

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.runtime_support import (
    RESPONSE_IMAGE_TRANSPORT_STORAGE_REF,
    build_response_image_payload,
)
from backend.nodes.video_runtime_support import require_frame_window_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.preview_display_outputs import (
    build_preview_run_artifact_object_key,
    read_preview_run_id,
)


def _frame_window_preview_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 frame-window.v1 采样后转换成 gallery-preview body。"""

    frame_window_payload = require_frame_window_payload(
        request.input_values.get("frames"),
        node_id=request.node_id,
    )
    title = _read_title(request.parameters.get("title"))
    sample_mode = _read_sample_mode(request.parameters.get("sample_mode"))
    max_items = _read_max_items(request.parameters.get("max_items"))
    response_transport_mode = _read_response_transport_mode(request.parameters.get("response_transport_mode"))

    sampled_items = _sample_frame_items(
        frame_items=frame_window_payload["items"],
        sample_mode=sample_mode,
        max_items=max_items,
    )
    preview_items: list[dict[str, object]] = []
    for sample_offset, frame_item in enumerate(sampled_items, start=1):
        preview_items.append(
            {
                "caption": _build_frame_caption(frame_item),
                "frame_index": int(frame_item["frame_index"]),
                "timestamp_ms": float(frame_item["timestamp_ms"]),
                "image": build_response_image_payload(
                    request,
                    image_payload=frame_item["image"],
                    response_transport_mode=response_transport_mode,
                    object_key=_build_preview_object_key(
                        request=request,
                        frame_item=frame_item,
                        sample_offset=sample_offset,
                        response_transport_mode=response_transport_mode,
                    ),
                    variant_name=f"frame-window-preview-{int(frame_item['frame_index']):06d}",
                ),
            }
        )

    body: dict[str, object] = {
        "type": "gallery-preview",
        "title": title,
        "items": preview_items,
        "total_count": int(frame_window_payload["count"]),
        "sample_count": len(preview_items),
        "sample_mode": sample_mode,
        "window_start_index": int(frame_window_payload["window_start_index"]),
        "window_end_index": int(frame_window_payload["window_end_index"]),
    }
    source_video = frame_window_payload.get("source_video")
    if isinstance(source_video, dict):
        body["source_video"] = dict(source_video)
    if not preview_items:
        body["empty_text"] = "当前帧窗口没有可显示帧。"
    return {"body": body}


def _sample_frame_items(
    *,
    frame_items: tuple[dict[str, object], ...],
    sample_mode: str,
    max_items: int,
) -> tuple[dict[str, object], ...]:
    """按采样模式选择一组预览帧。"""

    if len(frame_items) <= max_items:
        return frame_items
    if sample_mode == "head":
        return frame_items[:max_items]
    if max_items == 1:
        return (frame_items[0],)

    last_index = len(frame_items) - 1
    sampled_indices: list[int] = []
    for sample_index in range(max_items):
        normalized_index = int(round(sample_index * last_index / (max_items - 1)))
        if normalized_index not in sampled_indices:
            sampled_indices.append(normalized_index)
    while len(sampled_indices) < max_items:
        next_index = min(last_index, sampled_indices[-1] + 1)
        if next_index in sampled_indices:
            break
        sampled_indices.append(next_index)
    return tuple(frame_items[item_index] for item_index in sampled_indices[:max_items])


def _build_frame_caption(frame_item: dict[str, object]) -> str:
    """构造帧预览文案。"""

    return f"Frame {int(frame_item['frame_index'])} · {float(frame_item['timestamp_ms']):.1f} ms"


def _build_preview_object_key(
    *,
    request: WorkflowNodeExecutionRequest,
    frame_item: dict[str, object],
    sample_offset: int,
    response_transport_mode: str,
) -> str | None:
    """为 storage-ref 模式生成稳定 preview object key。"""

    if response_transport_mode != RESPONSE_IMAGE_TRANSPORT_STORAGE_REF:
        return None
    media_type = str(frame_item["image"].get("media_type") or "image/png")
    preview_run_id = read_preview_run_id(request.execution_metadata)
    if preview_run_id is not None:
        return build_preview_run_artifact_object_key(
            preview_run_id=preview_run_id,
            node_id=request.node_id,
            artifact_name=f"frame-window-preview-{int(frame_item['frame_index']):06d}",
            media_type=media_type,
        )

    workflow_run_id = str(request.execution_metadata.get("workflow_run_id") or "default-run")
    return (
        f"workflows/runtime/{workflow_run_id}/{request.node_id}/"
        f"frame-window-preview-{sample_offset:03d}-{int(frame_item['frame_index']):06d}"
        f"{_infer_extension_from_media_type(media_type)}"
    )


def _infer_extension_from_media_type(media_type: str) -> str:
    """根据媒体类型推断扩展名。"""

    guessed_extension = mimetypes.guess_extension(media_type.strip()) if isinstance(media_type, str) else None
    if isinstance(guessed_extension, str) and guessed_extension:
        return guessed_extension
    return ".png"


def _read_title(raw_value: object) -> str:
    """读取标题参数。"""

    if raw_value is None:
        return "Frame Window Preview"
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("frame-window-preview 的 title 必须是非空字符串")
    return raw_value.strip()


def _read_sample_mode(raw_value: object) -> str:
    """读取采样模式参数。"""

    if raw_value is None:
        return "uniform"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("frame-window-preview 的 sample_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"uniform", "head"}:
        raise InvalidRequestError("frame-window-preview 的 sample_mode 仅支持 uniform 或 head")
    return normalized_value


def _read_max_items(raw_value: object) -> int:
    """读取最大预览帧数。"""

    if raw_value is None:
        return 6
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
        raise InvalidRequestError("frame-window-preview 的 max_items 必须是正整数")
    return raw_value


def _read_response_transport_mode(raw_value: object) -> str:
    """读取图片返回方式。"""

    if raw_value is None:
        return "inline-base64"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("frame-window-preview 的 response_transport_mode 必须是字符串")
    normalized_value = raw_value.strip()
    if normalized_value not in {"inline-base64", "storage-ref"}:
        raise InvalidRequestError(
            "frame-window-preview 的 response_transport_mode 仅支持 inline-base64 或 storage-ref"
        )
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.frame-window-preview",
        display_name="Frame Window Preview",
        category="ui.preview",
        description="把 frame-window.v1 采样整理成 gallery-preview response body，方便在 workflow editor 中直接预览多帧结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="frames",
                display_name="Frames",
                payload_type_id="frame-window.v1",
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
                "title": {
                    "type": "string",
                    "title": "标题",
                    "description": "帧窗口预览卡片显示名称。",
                    "default": "Frame Window Preview",
                },
                "sample_mode": {
                    "type": "string",
                    "title": "采样模式",
                    "description": "uniform 均匀抽样整个窗口；head 只展示前几帧。",
                    "enum": ["uniform", "head"],
                    "default": "uniform",
                },
                "max_items": {
                    "type": "integer",
                    "title": "最大帧数",
                    "description": "最多输出多少张预览帧。",
                    "minimum": 1,
                    "default": 6,
                },
                "response_transport_mode": {
                    "type": "string",
                    "title": "返回方式",
                    "description": "inline-base64 直接携带图片；storage-ref 适合较大帧窗口或 Preview Run artifact 复用。",
                    "enum": ["inline-base64", "storage-ref"],
                    "default": "inline-base64",
                },
            },
        },
        capability_tags=("ui.preview", "response.body", "video.frame-window"),
    ),
    handler=_frame_window_preview_handler,
)
