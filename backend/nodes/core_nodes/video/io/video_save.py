"""视频保存节点。"""

from __future__ import annotations

from datetime import datetime
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
from backend.nodes.file_name_template import (
    render_file_name_template,
    require_file_name_suffix,
)
from backend.nodes.runtime_support import load_image_bytes_from_payload
from backend.nodes.save_node_contracts import (
    build_save_target_input_ports,
    build_save_target_parameter_input_bindings,
    build_save_target_parameter_properties,
    build_save_target_required_parameters,
    read_save_overwrite,
)
from backend.nodes.save_locations import (
    SAVE_LOCATION_OBJECT_STORE,
    build_save_template_context,
    resolve_required_save_directory,
    save_file,
)
from backend.nodes.video_runtime_support import (
    build_local_video_payload,
    build_storage_video_payload,
    encode_video_frames_with_backend,
    probe_video_metadata,
    read_video_tool_summary,
    require_frame_window_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _video_save_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 frame-window.v1 重新编码保存为 video-ref.v1。"""

    frame_window_payload = require_frame_window_payload(
        request.input_values.get("frames"),
        node_id=request.node_id,
    )
    fps = _resolve_output_fps(request, frame_window_payload=frame_window_payload)
    container = _read_container(request.parameters.get("container"))
    overwrite = read_save_overwrite(
        request.parameters.get("overwrite"),
        node_label="Save Video",
    )
    output_extension = ".avi" if container == "avi" else ".mp4"

    prepared_frame_items: list[dict[str, object]] = []
    for frame_item in frame_window_payload["items"]:
        image_payload, image_bytes = load_image_bytes_from_payload(
            request, image_payload=frame_item["image"]
        )
        prepared_frame_items.append(
            {
                "frame_index": int(frame_item["frame_index"]),
                "timestamp_ms": float(frame_item["timestamp_ms"]),
                "content": image_bytes,
                "media_type": str(image_payload["media_type"]),
            }
        )

    current_time = datetime.now().astimezone()
    format_context = build_save_template_context(
        request,
        current_time=current_time,
    )
    rendered_directory, save_location = resolve_required_save_directory(
        request,
        request.parameters.get("save_directory"),
        node_label="Save Video",
        current_time=current_time,
        context=format_context,
    )
    file_name = render_file_name_template(
        request.parameters.get("file_name"),
        node_label="Save Video",
        current_time=current_time,
        context=format_context,
    )
    suffix = require_file_name_suffix(
        file_name,
        node_label="Save Video",
        supported_suffixes={".avi", ".mp4"},
    )
    if suffix != output_extension:
        raise InvalidRequestError(
            "Save Video 文件扩展名与 container 不一致",
            details={
                "file_name": file_name,
                "container": container,
                "expected_extension": output_extension,
            },
        )
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
            file_name=file_name,
            overwrite=overwrite,
            increment_on_conflict=not overwrite,
        )
    video_payload = (
        build_storage_video_payload(
            object_key=str(saved_file.object_key or ""), metadata=metadata
        )
        if saved_file.kind == SAVE_LOCATION_OBJECT_STORE
        else build_local_video_payload(
            local_path=str(saved_file.local_path or ""), metadata=metadata
        )
    )
    return {
        "video": video_payload,
        "summary": build_value_payload(
            {
                "save_directory": rendered_directory,
                "file_name": file_name,
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
        if (
            isinstance(raw_fps, bool)
            or not isinstance(raw_fps, (int, float))
            or float(raw_fps) <= 0
        ):
            raise InvalidRequestError("video-save 的 fps 必须是大于 0 的数值")
        return float(raw_fps)
    source_video = frame_window_payload.get("source_video")
    if isinstance(source_video, dict):
        source_fps = source_video.get("fps")
        if (
            isinstance(source_fps, (int, float))
            and not isinstance(source_fps, bool)
            and float(source_fps) > 0
        ):
            return float(source_fps)
    items = frame_window_payload["items"]
    if len(items) >= 2:
        frame_span = int(items[-1]["frame_index"]) - int(items[0]["frame_index"])
        time_span_ms = float(items[-1]["timestamp_ms"]) - float(
            items[0]["timestamp_ms"]
        )
        if frame_span > 0 and time_span_ms > 0:
            return float(frame_span / (time_span_ms / 1000.0))
    return 5.0


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
            *build_save_target_input_ports(include_overwrite=True),
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
                **build_save_target_parameter_properties(
                    overwrite_default=False,
                    file_name_example=(
                        "video-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.mp4"
                    ),
                ),
                "container": {
                    "type": "string",
                    "enum": ["mp4", "avi"],
                    "default": "mp4",
                },
                "fps": {"type": "number", "minimum": 0},
            },
            "required": build_save_target_required_parameters(
                include_overwrite=True,
            ),
        },
        parameter_input_bindings=build_save_target_parameter_input_bindings(
            include_overwrite=True,
        ),
        capability_tags=("io.video", "video.output", "video.save"),
    ),
    handler=_video_save_handler,
)
