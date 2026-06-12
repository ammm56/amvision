"""视频保存节点。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.runtime_support import load_image_bytes_from_payload
from backend.nodes.video_runtime_support import (
    VIDEO_TRANSPORT_LOCAL_PATH,
    VIDEO_TRANSPORT_STORAGE,
    build_local_video_payload,
    build_runtime_video_object_key,
    build_storage_video_payload,
    encode_video_frames_with_backend,
    probe_video_metadata,
    read_video_tool_summary,
    require_dataset_storage,
    require_frame_window_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _video_save_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 frame-window.v1 重新编码保存为 video-ref.v1。"""

    frame_window_payload = require_frame_window_payload(
        request.input_values.get("frames"),
        node_id=request.node_id,
    )
    fps = _resolve_output_fps(request, frame_window_payload=frame_window_payload)
    container = _read_container(request.parameters.get("container"))
    overwrite = _read_optional_bool(request.parameters.get("overwrite"), default=True)
    output_transport_kind = _read_output_transport_kind(request.parameters.get("output_transport_kind"))
    output_extension = ".avi" if container == "avi" else ".mp4"

    prepared_frame_items: list[dict[str, object]] = []
    for frame_item in frame_window_payload["items"]:
        image_payload, image_bytes = load_image_bytes_from_payload(request, image_payload=frame_item["image"])
        prepared_frame_items.append(
            {
                "frame_index": int(frame_item["frame_index"]),
                "timestamp_ms": float(frame_item["timestamp_ms"]),
                "content": image_bytes,
                "media_type": str(image_payload["media_type"]),
            }
        )

    if output_transport_kind == VIDEO_TRANSPORT_LOCAL_PATH:
        local_path = _resolve_local_output_path(
            request=request,
            raw_local_path=request.parameters.get("local_path"),
            output_extension=output_extension,
            overwrite=overwrite,
        )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        encode_backend = encode_video_frames_with_backend(
            frame_items=prepared_frame_items,
            output_path=local_path,
            fps=fps,
            container=container,
        )
        metadata = probe_video_metadata(local_path)
        return {
            "video": build_local_video_payload(local_path=str(local_path), metadata=metadata),
            "summary": build_value_payload(
                {
                    "output_transport_kind": output_transport_kind,
                    "local_path": str(local_path),
                    "encode_backend": encode_backend,
                    **read_video_tool_summary(),
                    "frame_count": metadata["frame_count"],
                    "fps": metadata["fps"],
                    "width": metadata["width"],
                    "height": metadata["height"],
                    "duration_ms": metadata["duration_ms"],
                    "container": container,
                }
            ),
        }

    object_key = _resolve_storage_object_key(
        request=request,
        frame_window_payload=frame_window_payload,
        raw_object_key=request.parameters.get("object_key"),
        output_extension=output_extension,
    )
    dataset_storage = require_dataset_storage(request)
    with tempfile.TemporaryDirectory(prefix="amvision-video-save-") as temp_dir:
        temp_output_path = Path(temp_dir) / f"video-output{output_extension}"
        encode_backend = encode_video_frames_with_backend(
            frame_items=prepared_frame_items,
            output_path=temp_output_path,
            fps=fps,
            container=container,
        )
        if dataset_storage.resolve(object_key).exists() and not overwrite:
            raise InvalidRequestError(
                "video-save 目标 object_key 已存在，且当前节点未允许覆盖",
                details={"node_id": request.node_id, "object_key": object_key},
            )
        dataset_storage.copy_file(temp_output_path, object_key)
        metadata = probe_video_metadata(temp_output_path)
    return {
        "video": build_storage_video_payload(object_key=object_key, metadata=metadata),
        "summary": build_value_payload(
            {
                "output_transport_kind": output_transport_kind,
                "object_key": object_key,
                "encode_backend": encode_backend,
                **read_video_tool_summary(),
                "frame_count": metadata["frame_count"],
                "fps": metadata["fps"],
                "width": metadata["width"],
                "height": metadata["height"],
                "duration_ms": metadata["duration_ms"],
                "container": container,
            }
        ),
    }


def _resolve_output_fps(
    request: WorkflowNodeExecutionRequest,
    *,
    frame_window_payload: dict[str, object],
) -> float:
    """解析输出视频 fps。"""

    raw_fps = request.parameters.get("fps")
    if raw_fps is not None:
        if isinstance(raw_fps, bool) or not isinstance(raw_fps, (int, float)) or float(raw_fps) <= 0:
            raise InvalidRequestError("video-save 的 fps 必须是大于 0 的数值")
        return float(raw_fps)
    source_video = frame_window_payload.get("source_video")
    if isinstance(source_video, dict):
        source_fps = source_video.get("fps")
        if isinstance(source_fps, (int, float)) and not isinstance(source_fps, bool) and float(source_fps) > 0:
            return float(source_fps)
    items = frame_window_payload["items"]
    if len(items) >= 2:
        frame_span = int(items[-1]["frame_index"]) - int(items[0]["frame_index"])
        time_span_ms = float(items[-1]["timestamp_ms"]) - float(items[0]["timestamp_ms"])
        if frame_span > 0 and time_span_ms > 0:
            return float(frame_span / (time_span_ms / 1000.0))
    return 5.0


def _resolve_local_output_path(
    *,
    request: WorkflowNodeExecutionRequest,
    raw_local_path: object,
    output_extension: str,
    overwrite: bool,
) -> Path:
    """解析 local-path 输出位置。"""

    if not isinstance(raw_local_path, str) or not raw_local_path.strip():
        raise InvalidRequestError(
            "video-save 在 local-path 模式下要求 local_path 为非空字符串",
            details={"node_id": request.node_id},
        )
    output_path = Path(raw_local_path.strip()).expanduser()
    if not output_path.suffix:
        output_path = output_path.with_suffix(output_extension)
    output_path = output_path.resolve()
    if output_path.exists() and not overwrite:
        raise InvalidRequestError(
            "video-save 目标本地视频文件已存在，且当前节点未允许覆盖",
            details={"node_id": request.node_id, "local_path": str(output_path)},
        )
    return output_path


def _resolve_storage_object_key(
    *,
    request: WorkflowNodeExecutionRequest,
    frame_window_payload: dict[str, object],
    raw_object_key: object,
    output_extension: str,
) -> str:
    """解析 storage 输出 object_key。"""

    if isinstance(raw_object_key, str) and raw_object_key.strip():
        return raw_object_key.strip()
    source_video_payload = frame_window_payload.get("source_video")
    return build_runtime_video_object_key(
        request,
        source_video_payload=source_video_payload if isinstance(source_video_payload, dict) else None,
        variant_name="saved-video",
        output_extension=output_extension,
    )


def _read_optional_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError("video-save 的 overwrite 必须是布尔值")


def _read_output_transport_kind(raw_value: object) -> str:
    """读取输出传输方式。"""

    if raw_value is None:
        return VIDEO_TRANSPORT_STORAGE
    if not isinstance(raw_value, str):
        raise InvalidRequestError("video-save 的 output_transport_kind 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {VIDEO_TRANSPORT_STORAGE, VIDEO_TRANSPORT_LOCAL_PATH}:
        raise InvalidRequestError("video-save 的 output_transport_kind 仅支持 storage 或 local-path")
    return normalized_value


def _read_container(raw_value: object) -> str:
    """读取目标容器格式。"""

    if raw_value is None:
        return "mp4"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("video-save 的 container 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"mp4", "avi"}:
        raise InvalidRequestError("video-save 的 container 仅支持 mp4 或 avi")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.video-save",
        display_name="Save Video",
        category="io.video",
        description="把 frame-window.v1 重新编码并保存为本地视频或 ObjectStore video-ref.v1。",
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
                name="video",
                display_name="Video",
                payload_type_id="video-ref.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "output_transport_kind": {
                    "type": "string",
                    "enum": ["storage", "local-path"],
                    "default": "storage",
                },
                "object_key": {"type": "string", "default": ""},
                "local_path": {"type": "string", "default": ""},
                "container": {"type": "string", "enum": ["mp4", "avi"], "default": "mp4"},
                "fps": {"type": "number", "minimum": 0},
                "overwrite": {"type": "boolean", "default": True},
            },
        },
        capability_tags=("io.video", "video.output", "video.save"),
    ),
    handler=_video_save_handler,
)
