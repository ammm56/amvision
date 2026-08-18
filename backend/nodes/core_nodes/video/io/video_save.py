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
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import load_image_bytes_from_payload
from backend.nodes.save_locations import (
    SAVE_LOCATION_OBJECT_STORE,
    resolve_optional_save_location,
    save_file,
)
from backend.nodes.video_runtime_support import (
    build_local_video_payload,
    build_runtime_video_object_key,
    build_storage_video_payload,
    encode_video_frames_with_backend,
    probe_video_metadata,
    read_video_tool_summary,
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

    raw_save_location = _resolve_save_location_value(
        request=request,
        frame_window_payload=frame_window_payload,
        raw_save_location=request.parameters.get("save_location"),
        output_extension=output_extension,
    )
    save_location = resolve_optional_save_location(raw_save_location, scope="file")
    if save_location is None:
        raise InvalidRequestError("video-save 缺少有效保存位置")
    with tempfile.TemporaryDirectory(prefix="amvision-video-save-") as temp_dir:
        temp_output_path = Path(temp_dir) / f"video-output{output_extension}"
        encode_backend = encode_video_frames_with_backend(
            frame_items=prepared_frame_items,
            output_path=temp_output_path,
            fps=fps,
            container=container,
        )
        metadata = probe_video_metadata(temp_output_path)
        saved_file = save_file(
            request,
            save_location=save_location,
            source_path=temp_output_path,
            overwrite=overwrite,
        )
    video_payload = (
        build_storage_video_payload(object_key=str(saved_file.object_key or ""), metadata=metadata)
        if saved_file.kind == SAVE_LOCATION_OBJECT_STORE
        else build_local_video_payload(local_path=str(saved_file.local_path or ""), metadata=metadata)
    )
    return {
        "video": video_payload,
        "summary": build_value_payload(
            {
                "save_location": raw_save_location,
                "saved_output": saved_file.to_payload(),
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


def _resolve_save_location_value(
    *,
    request: WorkflowNodeExecutionRequest,
    frame_window_payload: dict[str, object],
    raw_save_location: object,
    output_extension: str,
) -> str:
    """解析统一保存位置，空值使用 runtime ObjectStore 默认路径。"""

    if isinstance(raw_save_location, str) and raw_save_location.strip():
        normalized_value = raw_save_location.strip()
        if Path(normalized_value).suffix:
            return normalized_value
        return f"{normalized_value}{output_extension}"
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
        category="core.io.video",
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
                "save_location": {
                    "type": "string",
                    "title": "保存位置",
                    "description": "相对路径保存到 ObjectStore，绝对路径保存到本地磁盘；为空时保存到 runtime 默认位置。",
                    "default": "",
                },
                "container": {"type": "string", "enum": ["mp4", "avi"], "default": "mp4"},
                "fps": {"type": "number", "minimum": 0},
                "overwrite": {"type": "boolean", "default": True},
            },
        },
        capability_tags=("io.video", "video.output", "video.save"),
    ),
    handler=_video_save_handler,
)
