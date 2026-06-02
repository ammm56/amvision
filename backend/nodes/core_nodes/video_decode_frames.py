"""视频解码为帧窗口节点。"""

from __future__ import annotations

from typing import Any

import cv2

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.runtime_support import register_image_bytes
from backend.nodes.video_runtime_support import require_video_payload, resolve_video_source_path
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _video_decode_frames_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按范围把视频解码为 frame-window.v1。"""

    video_payload = require_video_payload(request.input_values.get("video"))
    video_path = resolve_video_source_path(request, video_payload=video_payload)
    frame_count = int(video_payload.get("frame_count") or 0)
    start_frame = _read_optional_non_negative_int(request.parameters.get("start_frame"), default=0)
    end_frame = _read_optional_non_negative_int(
        request.parameters.get("end_frame"),
        default=max(start_frame, frame_count - 1) if frame_count > 0 else start_frame,
    )
    step = _read_positive_int(request.parameters.get("step"), default=1)
    max_frames = _read_positive_int(request.parameters.get("max_frames"), default=16)
    encode_format = _read_encode_format(request.parameters.get("encode_format"))

    if end_frame < start_frame:
        raise InvalidRequestError(
            "video-decode-frames 要求 end_frame 不能小于 start_frame",
            details={"node_id": request.node_id, "start_frame": start_frame, "end_frame": end_frame},
        )

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise InvalidRequestError(
            "无法打开指定视频文件",
            details={"node_id": request.node_id, "video_path": str(video_path)},
        )
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_items: list[dict[str, Any]] = []
        for frame_index in range(start_frame, end_frame + 1, step):
            if len(frame_items) >= max_frames:
                break
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = capture.read()
            if not success or frame is None:
                raise InvalidRequestError(
                    "视频帧解码失败",
                    details={"node_id": request.node_id, "video_path": str(video_path), "frame_index": frame_index},
                )
            file_suffix = ".png" if encode_format == "png" else ".jpg"
            media_type = "image/png" if encode_format == "png" else "image/jpeg"
            encode_success, encoded = cv2.imencode(file_suffix, frame)
            if not encode_success:
                raise InvalidRequestError(
                    "视频帧编码失败",
                    details={"node_id": request.node_id, "video_path": str(video_path), "frame_index": frame_index},
                )
            image_payload = register_image_bytes(
                request,
                content=encoded.tobytes(),
                media_type=media_type,
                width=int(frame.shape[1]),
                height=int(frame.shape[0]),
            )
            timestamp_ms = float((frame_index / fps) * 1000.0) if fps > 0 else 0.0
            frame_items.append(
                {
                    "frame_index": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "image": image_payload,
                }
            )
    finally:
        capture.release()

    frame_window = {
        "source_video": video_payload,
        "count": len(frame_items),
        "window_start_index": frame_items[0]["frame_index"] if frame_items else start_frame,
        "window_end_index": frame_items[-1]["frame_index"] if frame_items else start_frame,
        "items": frame_items,
    }
    return {
        "frames": frame_window,
        "summary": build_value_payload(
            {
                "video_path": str(video_path),
                "decoded_count": len(frame_items),
                "start_frame": start_frame,
                "end_frame": end_frame,
                "step": step,
                "max_frames": max_frames,
                "encode_format": encode_format,
            }
        ),
    }


def _read_optional_non_negative_int(raw_value: object, *, default: int) -> int:
    """读取可选非负整数参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError("video-decode-frames 的整数参数必须是非负整数")
    return raw_value


def _read_positive_int(raw_value: object, *, default: int) -> int:
    """读取正整数参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
        raise InvalidRequestError("video-decode-frames 的 step/max_frames 必须是正整数")
    return raw_value


def _read_encode_format(raw_value: object) -> str:
    """读取输出编码格式。"""

    if raw_value is None:
        return "png"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("video-decode-frames 的 encode_format 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"png", "jpg", "jpeg"}:
        raise InvalidRequestError("video-decode-frames 的 encode_format 仅支持 png 或 jpg")
    return "jpg" if normalized_value == "jpeg" else normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.video-decode-frames",
        display_name="Decode Video Frames",
        category="io.video",
        description="按范围把 video-ref.v1 解码成 frame-window.v1，供多帧模型或后续单帧节点复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="video",
                display_name="Video",
                payload_type_id="video-ref.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="frames",
                display_name="Frames",
                payload_type_id="frame-window.v1",
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
                "start_frame": {"type": "integer", "minimum": 0, "default": 0},
                "end_frame": {"type": "integer", "minimum": 0},
                "step": {"type": "integer", "minimum": 1, "default": 1},
                "max_frames": {"type": "integer", "minimum": 1, "default": 16},
                "encode_format": {
                    "type": "string",
                    "enum": ["png", "jpg"],
                    "default": "png",
                },
            },
        },
        capability_tags=("io.video", "video.decode", "video.frame-window"),
    ),
    handler=_video_decode_frames_handler,
)
