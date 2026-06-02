"""视频 workflow 节点共享 helper。"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import cv2
import numpy as np

from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.execution_cleanup import register_dataset_storage_object_cleanup
from backend.service.application.workflows.preview_display_outputs import (
    build_preview_run_artifact_object_key,
    read_preview_run_id,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


VIDEO_TRANSPORT_LOCAL_PATH = "local-path"
VIDEO_TRANSPORT_STORAGE = "storage"
RESPONSE_VIDEO_TRANSPORT_STORAGE_REF = "storage-ref"
VIDEO_TOOL_FFMPEG = "ffmpeg"
VIDEO_TOOL_FFPROBE = "ffprobe"
_APP_ROOT_DIR = Path(__file__).resolve().parents[2]


def resolve_video_tool_path(tool_name: str) -> Path | None:
    """解析视频工具可执行文件路径。"""

    normalized_tool_name = tool_name.strip().lower()
    if normalized_tool_name not in {VIDEO_TOOL_FFMPEG, VIDEO_TOOL_FFPROBE}:
        raise InvalidRequestError(
            "当前视频工具名称不受支持",
            details={"tool_name": tool_name},
        )

    for candidate_path in _iter_video_tool_candidates(normalized_tool_name):
        if candidate_path.is_file():
            return candidate_path.resolve()
    fallback_path = shutil.which(_tool_file_name(normalized_tool_name))
    if fallback_path:
        return Path(fallback_path).resolve()
    return None


def require_video_payload(payload: object) -> dict[str, object]:
    """校验并规范化 video-ref payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("视频节点要求 video-ref payload 必须是对象")
    normalized_payload = dict(payload)
    transport_kind = normalized_payload.get("transport_kind")
    normalized_transport_kind = transport_kind.strip() if isinstance(transport_kind, str) else ""
    local_path = normalized_payload.get("local_path")
    object_key = normalized_payload.get("object_key")

    if not normalized_transport_kind:
        if isinstance(local_path, str) and local_path.strip():
            normalized_transport_kind = VIDEO_TRANSPORT_LOCAL_PATH
        elif isinstance(object_key, str) and object_key.strip():
            normalized_transport_kind = VIDEO_TRANSPORT_STORAGE

    if normalized_transport_kind not in {VIDEO_TRANSPORT_LOCAL_PATH, VIDEO_TRANSPORT_STORAGE}:
        raise InvalidRequestError("video-ref payload 缺少有效 transport_kind")

    normalized_payload["transport_kind"] = normalized_transport_kind
    if normalized_transport_kind == VIDEO_TRANSPORT_LOCAL_PATH:
        if not isinstance(local_path, str) or not local_path.strip():
            raise InvalidRequestError("local-path video-ref payload 缺少有效 local_path")
        normalized_payload["local_path"] = str(Path(local_path.strip()).expanduser())
        normalized_payload.pop("object_key", None)
        media_type = normalized_payload.get("media_type")
        if not isinstance(media_type, str) or not media_type.strip():
            normalized_payload["media_type"] = infer_video_media_type(normalized_payload["local_path"])
    else:
        if not isinstance(object_key, str) or not object_key.strip():
            raise InvalidRequestError("storage video-ref payload 缺少有效 object_key")
        normalized_payload["object_key"] = object_key.strip()
        normalized_payload.pop("local_path", None)
        media_type = normalized_payload.get("media_type")
        if not isinstance(media_type, str) or not media_type.strip():
            normalized_payload["media_type"] = infer_video_media_type(normalized_payload["object_key"])

    for field_name in ("frame_count", "width", "height"):
        normalized_value = _normalize_optional_non_negative_int(normalized_payload.get(field_name))
        if normalized_value is None:
            normalized_payload.pop(field_name, None)
        else:
            normalized_payload[field_name] = normalized_value
    for field_name in ("fps", "duration_ms"):
        normalized_value = _normalize_optional_non_negative_number(normalized_payload.get(field_name))
        if normalized_value is None:
            normalized_payload.pop(field_name, None)
        else:
            normalized_payload[field_name] = normalized_value
    return normalized_payload


def require_frame_window_payload(
    payload: object,
    *,
    node_id: str,
    field_name: str = "frames",
    allow_empty: bool = False,
) -> dict[str, object]:
    """校验 frame-window.v1 payload 并返回规范化结果。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            f"{field_name} payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or (not raw_items and not allow_empty):
        expected_text = "数组" if allow_empty else "非空数组"
        raise InvalidRequestError(
            f"{field_name}.items 必须是{expected_text}",
            details={"node_id": node_id},
        )
    normalized_items: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError(
                f"{field_name}.items 的每一项都必须是对象",
                details={"node_id": node_id, "item_index": item_index},
            )
        frame_index = raw_item.get("frame_index")
        timestamp_ms = raw_item.get("timestamp_ms")
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            raise InvalidRequestError(
                f"{field_name}.items.frame_index 必须是非负整数",
                details={"node_id": node_id, "item_index": item_index, "frame_index": frame_index},
            )
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, (int, float))
            or float(timestamp_ms) < 0
        ):
            raise InvalidRequestError(
                f"{field_name}.items.timestamp_ms 必须是非负数",
                details={"node_id": node_id, "item_index": item_index, "timestamp_ms": timestamp_ms},
            )
        normalized_items.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": float(timestamp_ms),
                "image": require_image_payload(raw_item.get("image")),
            }
        )
    normalized_payload: dict[str, object] = {
        "count": len(normalized_items),
        "items": tuple(normalized_items),
    }
    if payload.get("source_video") is not None:
        normalized_payload["source_video"] = require_video_payload(payload.get("source_video"))
    else:
        normalized_payload["source_video"] = None
    normalized_payload["window_start_index"] = normalized_items[0]["frame_index"] if normalized_items else 0
    normalized_payload["window_end_index"] = normalized_items[-1]["frame_index"] if normalized_items else 0
    return normalized_payload


def resolve_video_source_path(
    request: WorkflowNodeExecutionRequest,
    *,
    video_payload: object,
) -> Path:
    """把 video-ref payload 解析为当前机器可读取的本地绝对路径。"""

    normalized_payload = require_video_payload(video_payload)
    if normalized_payload["transport_kind"] == VIDEO_TRANSPORT_LOCAL_PATH:
        local_path = Path(str(normalized_payload["local_path"])).expanduser().resolve()
        if not local_path.is_file():
            raise InvalidRequestError(
                "本地视频文件不存在",
                details={"node_id": request.node_id, "local_path": str(local_path)},
            )
        return local_path

    dataset_storage = require_dataset_storage(request)
    source_path = dataset_storage.resolve(str(normalized_payload["object_key"]))
    if not source_path.is_file():
        raise InvalidRequestError(
            "视频节点引用的 object_key 不存在",
            details={"node_id": request.node_id, "object_key": normalized_payload["object_key"]},
        )
    return source_path


def probe_video_metadata(video_path: Path) -> dict[str, object]:
    """探测视频基础元数据。"""

    metadata, _backend = probe_video_metadata_with_backend(video_path)
    return metadata


def probe_video_metadata_with_backend(video_path: Path) -> tuple[dict[str, object], str]:
    """探测视频基础元数据，并返回实际使用的后端。"""

    ffprobe_path = resolve_video_tool_path(VIDEO_TOOL_FFPROBE)
    if ffprobe_path is not None:
        try:
            return _probe_video_metadata_with_ffprobe(video_path, ffprobe_path=ffprobe_path), VIDEO_TOOL_FFPROBE
        except Exception:
            pass
    return _probe_video_metadata_with_opencv(video_path), "opencv"


def decode_video_frames_with_backend(
    video_path: Path,
    *,
    start_frame: int,
    end_frame: int,
    step: int,
    max_frames: int,
    encode_format: str,
    fps_hint: float = 0.0,
) -> tuple[list[dict[str, Any]], str]:
    """按范围把视频解码为帧信息列表，并返回实际使用的后端。"""

    selected_frame_indices = list(range(start_frame, end_frame + 1, step))[:max_frames]
    if not selected_frame_indices:
        return [], VIDEO_TOOL_FFMPEG

    ffmpeg_path = resolve_video_tool_path(VIDEO_TOOL_FFMPEG)
    if ffmpeg_path is not None:
        try:
            return (
                _decode_video_frames_with_ffmpeg(
                    video_path,
                    ffmpeg_path=ffmpeg_path,
                    frame_indices=selected_frame_indices,
                    encode_format=encode_format,
                    fps_hint=fps_hint,
                ),
                VIDEO_TOOL_FFMPEG,
            )
        except Exception:
            pass
    return (
        _decode_video_frames_with_opencv(
            video_path,
            frame_indices=selected_frame_indices,
            encode_format=encode_format,
            fps_hint=fps_hint,
        ),
        "opencv",
    )


def encode_video_frames_with_backend(
    *,
    frame_items: list[dict[str, Any]],
    output_path: Path,
    fps: float,
    container: str,
) -> str:
    """把帧序列编码为视频文件，并返回实际使用的后端。"""

    if not frame_items:
        raise InvalidRequestError("video-save 要求至少包含一帧")
    if fps <= 0:
        raise InvalidRequestError("video-save 要求 fps 必须大于 0")
    normalized_container = container.strip().lower()
    if normalized_container not in {"mp4", "avi"}:
        raise InvalidRequestError(
            "video-save 当前仅支持 mp4 或 avi 容器",
            details={"container": container},
        )

    ffmpeg_path = resolve_video_tool_path(VIDEO_TOOL_FFMPEG)
    if ffmpeg_path is not None:
        try:
            _encode_video_frames_with_ffmpeg(
                frame_items=frame_items,
                output_path=output_path,
                fps=fps,
                container=normalized_container,
                ffmpeg_path=ffmpeg_path,
            )
            return VIDEO_TOOL_FFMPEG
        except Exception:
            pass
    _encode_video_frames_with_opencv(
        frame_items=frame_items,
        output_path=output_path,
        fps=fps,
        container=normalized_container,
    )
    return "opencv"


def read_video_tool_summary() -> dict[str, object]:
    """返回当前视频工具链解析结果，供 summary 使用。"""

    ffprobe_path = resolve_video_tool_path(VIDEO_TOOL_FFPROBE)
    ffmpeg_path = resolve_video_tool_path(VIDEO_TOOL_FFMPEG)
    return {
        "ffprobe_path": str(ffprobe_path) if ffprobe_path is not None else None,
        "ffmpeg_path": str(ffmpeg_path) if ffmpeg_path is not None else None,
    }


def infer_video_runtime_platform() -> str:
    """推断当前视频运行时平台目录名。"""

    if sys.platform.startswith("win"):
        return "windows-x64"
    if sys.platform.startswith("linux"):
        return "linux-x64"
    return "unknown"


def _probe_video_metadata_with_ffprobe(video_path: Path, *, ffprobe_path: Path) -> dict[str, object]:
    """通过 ffprobe 读取视频元数据。"""

    completed_process = _run_video_tool_command(
        [
            str(ffprobe_path),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        error_title="ffprobe 视频元数据探测失败",
        details={"video_path": str(video_path), "tool_path": str(ffprobe_path)},
    )
    parsed_payload = json.loads(completed_process.stdout or "{}")
    streams = parsed_payload.get("streams") if isinstance(parsed_payload, dict) else None
    if not isinstance(streams, list) or not streams:
        raise InvalidRequestError(
            "ffprobe 没有返回可用视频流",
            details={"video_path": str(video_path), "tool_path": str(ffprobe_path)},
        )
    first_stream = streams[0] if isinstance(streams[0], dict) else {}
    format_payload = parsed_payload.get("format") if isinstance(parsed_payload.get("format"), dict) else {}

    width = _normalize_optional_non_negative_int(first_stream.get("width")) or 0
    height = _normalize_optional_non_negative_int(first_stream.get("height")) or 0
    fps = _parse_ffprobe_frame_rate(
        first_stream.get("avg_frame_rate") or first_stream.get("r_frame_rate") or "0/0"
    )
    duration_seconds = _normalize_optional_non_negative_number(
        first_stream.get("duration") or format_payload.get("duration")
    ) or 0.0
    frame_count = _normalize_optional_non_negative_int(first_stream.get("nb_frames")) or 0
    if frame_count <= 0 and fps > 0 and duration_seconds > 0:
        frame_count = max(0, int(round(duration_seconds * fps)))
    duration_ms = duration_seconds * 1000.0 if duration_seconds > 0 else 0.0
    return {
        "frame_count": frame_count,
        "fps": float(fps),
        "width": width,
        "height": height,
        "duration_ms": float(duration_ms),
    }


def _probe_video_metadata_with_opencv(video_path: Path) -> dict[str, object]:
    """通过 OpenCV 读取视频元数据。"""

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise InvalidRequestError(
            "无法打开指定视频文件",
            details={"video_path": str(video_path)},
        )
    try:
        raw_frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        raw_fps = capture.get(cv2.CAP_PROP_FPS)
        raw_width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        raw_height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    finally:
        capture.release()

    frame_count = max(0, int(raw_frame_count or 0))
    fps = float(raw_fps) if raw_fps and raw_fps > 0 else 0.0
    width = max(0, int(raw_width or 0))
    height = max(0, int(raw_height or 0))
    duration_ms = float((frame_count / fps) * 1000.0) if frame_count > 0 and fps > 0 else 0.0
    return {
        "frame_count": frame_count,
        "fps": fps,
        "width": width,
        "height": height,
        "duration_ms": duration_ms,
    }


def _decode_video_frames_with_ffmpeg(
    video_path: Path,
    *,
    ffmpeg_path: Path,
    frame_indices: list[int],
    encode_format: str,
    fps_hint: float,
) -> list[dict[str, Any]]:
    """通过 ffmpeg 解码指定帧。"""

    if not frame_indices:
        return []
    output_suffix = ".png" if encode_format == "png" else ".jpg"
    media_type = "image/png" if encode_format == "png" else "image/jpeg"
    select_filter = "select=" + "+".join(f"eq(n\\,{frame_index})" for frame_index in frame_indices)
    with tempfile.TemporaryDirectory(prefix="amvision-video-decode-") as temp_dir:
        output_pattern = str(Path(temp_dir) / f"frame_%06d{output_suffix}")
        command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            select_filter,
            "-vsync",
            "0",
            "-frames:v",
            str(len(frame_indices)),
        ]
        if encode_format == "jpg":
            command.extend(["-q:v", "2"])
        command.append(output_pattern)
        _run_video_tool_command(
            command,
            error_title="ffmpeg 视频帧解码失败",
            details={"video_path": str(video_path), "tool_path": str(ffmpeg_path)},
        )
        output_files = sorted(Path(temp_dir).glob(f"frame_*{output_suffix}"))
        if len(output_files) != len(frame_indices):
            raise InvalidRequestError(
                "ffmpeg 解码输出帧数量异常",
                details={
                    "video_path": str(video_path),
                    "expected_count": len(frame_indices),
                    "actual_count": len(output_files),
                },
            )

        frame_items: list[dict[str, Any]] = []
        for frame_index, output_file in zip(frame_indices, output_files, strict=False):
            content = output_file.read_bytes()
            image = cv2.imread(str(output_file), cv2.IMREAD_COLOR)
            if image is None:
                raise InvalidRequestError(
                    "ffmpeg 输出帧读取失败",
                    details={"video_path": str(video_path), "output_file": str(output_file)},
                )
            timestamp_ms = float((frame_index / fps_hint) * 1000.0) if fps_hint > 0 else 0.0
            frame_items.append(
                {
                    "frame_index": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "content": content,
                    "media_type": media_type,
                    "width": int(image.shape[1]),
                    "height": int(image.shape[0]),
                }
            )
    return frame_items


def _decode_video_frames_with_opencv(
    video_path: Path,
    *,
    frame_indices: list[int],
    encode_format: str,
    fps_hint: float,
) -> list[dict[str, Any]]:
    """通过 OpenCV 解码指定帧。"""

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise InvalidRequestError(
            "无法打开指定视频文件",
            details={"video_path": str(video_path)},
        )
    try:
        frame_items: list[dict[str, Any]] = []
        file_suffix = ".png" if encode_format == "png" else ".jpg"
        media_type = "image/png" if encode_format == "png" else "image/jpeg"
        for frame_index in frame_indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = capture.read()
            if not success or frame is None:
                raise InvalidRequestError(
                    "视频帧解码失败",
                    details={"video_path": str(video_path), "frame_index": frame_index},
                )
            encode_success, encoded = cv2.imencode(file_suffix, frame)
            if not encode_success:
                raise InvalidRequestError(
                    "视频帧编码失败",
                    details={"video_path": str(video_path), "frame_index": frame_index},
                )
            timestamp_ms = float((frame_index / fps_hint) * 1000.0) if fps_hint > 0 else 0.0
            frame_items.append(
                {
                    "frame_index": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "content": encoded.tobytes(),
                    "media_type": media_type,
                    "width": int(frame.shape[1]),
                    "height": int(frame.shape[0]),
                }
            )
    finally:
        capture.release()
    return frame_items


def _encode_video_frames_with_ffmpeg(
    *,
    frame_items: list[dict[str, Any]],
    output_path: Path,
    fps: float,
    container: str,
    ffmpeg_path: Path,
) -> None:
    """通过 ffmpeg 把帧序列编码为视频。"""

    with tempfile.TemporaryDirectory(prefix="amvision-video-encode-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        for frame_offset, frame_item in enumerate(frame_items, start=1):
            frame_matrix = _decode_video_frame_content(content=bytes(frame_item["content"]))
            output_file = temp_dir_path / f"frame_{frame_offset:06d}.png"
            encode_success, encoded_png = cv2.imencode(".png", frame_matrix)
            if encode_success is not True:
                raise InvalidRequestError(
                    "video-save 在 ffmpeg 输入准备阶段无法编码 PNG 帧",
                    details={"frame_offset": frame_offset},
                )
            output_file.write_bytes(encoded_png.tobytes())

        command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            f"{float(fps):.6f}",
            "-i",
            str(temp_dir_path / "frame_%06d.png"),
            "-an",
        ]
        if container == "avi":
            command.extend(["-c:v", "mjpeg"])
        else:
            command.extend(["-c:v", "mpeg4", "-pix_fmt", "yuv420p"])
        command.append(str(output_path))
        _run_video_tool_command(
            command,
            error_title="ffmpeg 视频编码失败",
            details={"output_path": str(output_path), "tool_path": str(ffmpeg_path)},
        )


def _encode_video_frames_with_opencv(
    *,
    frame_items: list[dict[str, Any]],
    output_path: Path,
    fps: float,
    container: str,
) -> None:
    """通过 OpenCV 把帧序列编码为视频。"""

    first_frame = _decode_video_frame_content(content=bytes(frame_items[0]["content"]))
    frame_width = int(first_frame.shape[1])
    frame_height = int(first_frame.shape[0])
    fourcc = cv2.VideoWriter_fourcc(*("MJPG" if container == "avi" else "mp4v"))
    writer = cv2.VideoWriter(str(output_path), fourcc, float(fps), (frame_width, frame_height))
    if writer.isOpened() is not True:
        raise InvalidRequestError(
            "OpenCV 无法创建目标视频文件",
            details={"output_path": str(output_path), "fps": fps, "container": container},
        )
    try:
        for frame_item in frame_items:
            frame_matrix = _decode_video_frame_content(content=bytes(frame_item["content"]))
            if int(frame_matrix.shape[1]) != frame_width or int(frame_matrix.shape[0]) != frame_height:
                frame_matrix = cv2.resize(frame_matrix, (frame_width, frame_height), interpolation=cv2.INTER_LINEAR)
            writer.write(frame_matrix)
    finally:
        writer.release()


def _decode_video_frame_content(*, content: bytes) -> Any:
    """把单帧图片字节解码为 OpenCV 矩阵。"""

    if not content:
        raise InvalidRequestError("视频帧图片字节不能为空")
    decoded_frame = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded_frame is None:
        raise InvalidRequestError("无法解码视频帧图片字节")
    return decoded_frame


def build_local_video_payload(*, local_path: str, metadata: dict[str, object] | None = None) -> dict[str, object]:
    """构建 local-path 形式的 video-ref payload。"""

    normalized_local_path = str(Path(local_path).expanduser())
    payload: dict[str, object] = {
        "transport_kind": VIDEO_TRANSPORT_LOCAL_PATH,
        "local_path": normalized_local_path,
        "media_type": infer_video_media_type(normalized_local_path),
    }
    if metadata:
        for field_name in ("frame_count", "fps", "width", "height", "duration_ms"):
            if field_name in metadata and metadata[field_name] is not None:
                payload[field_name] = metadata[field_name]
    return require_video_payload(payload)


def build_storage_video_payload(*, object_key: str, metadata: dict[str, object] | None = None) -> dict[str, object]:
    """构建 storage 形式的 video-ref payload。"""

    normalized_object_key = object_key.strip() if isinstance(object_key, str) else ""
    if not normalized_object_key:
        raise InvalidRequestError("storage video-ref payload 要求 object_key 不能为空")
    payload: dict[str, object] = {
        "transport_kind": VIDEO_TRANSPORT_STORAGE,
        "object_key": normalized_object_key,
        "media_type": infer_video_media_type(normalized_object_key),
    }
    if metadata:
        for field_name in ("frame_count", "fps", "width", "height", "duration_ms"):
            if field_name in metadata and metadata[field_name] is not None:
                payload[field_name] = metadata[field_name]
    return require_video_payload(payload)


def build_response_video_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    video_payload: object,
    object_key: str | None = None,
    variant_name: str = "response-video",
    overwrite: bool = True,
) -> dict[str, object]:
    """把内部 video-ref payload 转换成对外 JSON 安全的视频响应结构。"""

    stored_payload = materialize_video_storage_payload(
        request,
        source_payload=video_payload,
        object_key=object_key,
        overwrite=overwrite,
        variant_name=variant_name,
    )
    response_video: dict[str, object] = {
        "transport_kind": RESPONSE_VIDEO_TRANSPORT_STORAGE_REF,
        "object_key": str(stored_payload["object_key"]),
        "media_type": str(stored_payload["media_type"]),
    }
    for field_name in ("frame_count", "fps", "width", "height", "duration_ms"):
        if stored_payload.get(field_name) is not None:
            response_video[field_name] = stored_payload[field_name]
    return response_video


def materialize_video_storage_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    source_payload: object,
    object_key: str | None,
    overwrite: bool,
    variant_name: str,
) -> dict[str, object]:
    """确保 video-ref 已落到 ObjectStore，并返回 storage 形式 payload。"""

    normalized_source_payload = require_video_payload(source_payload)
    source_object_key = _normalize_optional_text(normalized_source_payload.get("object_key"))
    if (
        object_key is None
        and normalized_source_payload["transport_kind"] == VIDEO_TRANSPORT_STORAGE
        and source_object_key is not None
    ):
        return build_storage_video_payload(object_key=source_object_key, metadata=normalized_source_payload)

    target_object_key = object_key or _build_default_video_target_object_key(
        request,
        normalized_source_payload=normalized_source_payload,
        variant_name=variant_name,
    )
    if source_object_key is not None and target_object_key == source_object_key:
        return build_storage_video_payload(object_key=target_object_key, metadata=normalized_source_payload)

    dataset_storage = require_dataset_storage(request)
    target_path = dataset_storage.resolve(target_object_key)
    if target_path.exists() and not overwrite:
        raise InvalidRequestError(
            "视频保存目标已存在，且当前节点未允许覆盖",
            details={"node_id": request.node_id, "object_key": target_object_key},
        )
    source_path = resolve_video_source_path(request, video_payload=normalized_source_payload)
    dataset_storage.copy_file(source_path, target_object_key)
    _register_temporary_runtime_video_cleanup(
        request,
        object_key=target_object_key,
        was_generated=object_key is None,
    )
    return build_storage_video_payload(object_key=target_object_key, metadata=normalized_source_payload)


def build_runtime_video_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    source_video_payload: dict[str, object] | None,
    variant_name: str,
    output_extension: str,
) -> str:
    """基于当前执行上下文生成视频 object key。"""

    workflow_run_id = str(request.execution_metadata.get("workflow_run_id") or "default-run")
    source_stem = "video"
    if source_video_payload is not None:
        normalized_source_video = require_video_payload(source_video_payload)
        source_reference = normalized_source_video.get("object_key") or normalized_source_video.get("local_path")
        if isinstance(source_reference, str) and source_reference.strip():
            source_stem = Path(source_reference).stem or source_stem
    normalized_variant_name = variant_name.strip().replace(" ", "-") or "output"
    return (
        f"workflows/runtime/{workflow_run_id}/{request.node_id}/"
        f"{source_stem}-{normalized_variant_name}{output_extension}"
    )


def resolve_video_path_from_request(
    request: WorkflowNodeExecutionRequest,
    *,
    parameter_name: str = "local_path",
    input_name: str = "path",
) -> Path:
    """从输入端口或参数读取本地视频路径。"""

    input_payload = request.input_values.get(input_name)
    if input_payload is not None:
        raw_value = require_value_payload(input_payload, field_name=input_name)["value"]
    else:
        raw_value = request.parameters.get(parameter_name)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            "视频节点要求 local_path 必须是非空字符串",
            details={"node_id": request.node_id, "parameter_name": parameter_name},
        )
    resolved_path = Path(raw_value.strip()).expanduser().resolve()
    if not resolved_path.is_file():
        raise InvalidRequestError(
            "本地视频文件不存在",
            details={"node_id": request.node_id, "local_path": str(resolved_path)},
        )
    return resolved_path


def infer_video_media_type(path_like: str) -> str:
    """根据路径推断视频媒体类型。"""

    guessed_media_type, _ = mimetypes.guess_type(path_like)
    if isinstance(guessed_media_type, str) and guessed_media_type:
        return guessed_media_type
    return "video/mp4"


def require_dataset_storage(request: WorkflowNodeExecutionRequest) -> LocalDatasetStorage:
    """从执行元数据中读取 LocalDatasetStorage。"""

    dataset_storage = request.execution_metadata.get("dataset_storage")
    if not isinstance(dataset_storage, LocalDatasetStorage):
        raise ServiceConfigurationError(
            "当前视频节点执行缺少 LocalDatasetStorage 上下文",
            details={"node_id": request.node_id, "required_metadata": "dataset_storage"},
        )
    return dataset_storage


def _build_default_video_target_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    normalized_source_payload: dict[str, object],
    variant_name: str,
) -> str:
    """按当前执行上下文为视频生成默认 object key。"""

    source_object_key = _normalize_optional_text(normalized_source_payload.get("object_key"))
    media_type = str(normalized_source_payload.get("media_type") or "video/mp4")
    preview_run_id = read_preview_run_id(request.execution_metadata)
    if preview_run_id is not None:
        return build_preview_run_artifact_object_key(
            preview_run_id=preview_run_id,
            node_id=request.node_id,
            artifact_name=variant_name,
            media_type=media_type,
        )

    output_extension = _infer_video_file_extension_from_media_type(media_type)
    if source_object_key is not None:
        source_reference_payload: dict[str, object] | None = {
            "transport_kind": VIDEO_TRANSPORT_STORAGE,
            "object_key": source_object_key,
            "media_type": media_type,
        }
    else:
        local_path = _normalize_optional_text(normalized_source_payload.get("local_path")) or "video.mp4"
        source_reference_payload = {
            "transport_kind": VIDEO_TRANSPORT_LOCAL_PATH,
            "local_path": local_path,
            "media_type": media_type,
        }
    return build_runtime_video_object_key(
        request,
        source_video_payload=source_reference_payload,
        variant_name=variant_name,
        output_extension=output_extension,
    )


def _register_temporary_runtime_video_cleanup(
    request: WorkflowNodeExecutionRequest,
    *,
    object_key: str,
    was_generated: bool,
) -> None:
    """为自动生成的视频 object key 登记执行结束后的临时清理。"""

    if not was_generated:
        return
    normalized_object_key = _normalize_optional_text(object_key)
    if normalized_object_key is None:
        return
    if not _is_temporary_runtime_video_object_key(request, object_key=normalized_object_key):
        return
    register_dataset_storage_object_cleanup(
        request.execution_metadata,
        object_key=normalized_object_key,
    )


def _is_temporary_runtime_video_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    object_key: str,
) -> bool:
    """判断视频 object key 是否属于当前 workflow run 的临时目录。"""

    workflow_run_id = str(request.execution_metadata.get("workflow_run_id") or "default-run")
    return object_key.startswith(f"workflows/runtime/{workflow_run_id}/")


def _iter_video_tool_candidates(tool_name: str) -> list[Path]:
    """构造视频工具候选路径列表。"""

    tool_file_name = _tool_file_name(tool_name)
    platform_dir_name = infer_video_runtime_platform()
    candidate_paths: list[Path] = []

    explicit_tool_env_var = "AMVISION_FFPROBE_PATH" if tool_name == VIDEO_TOOL_FFPROBE else "AMVISION_FFMPEG_PATH"
    explicit_tool_path = os.environ.get(explicit_tool_env_var)
    if explicit_tool_path:
        candidate_paths.append(Path(explicit_tool_path).expanduser())

    explicit_bin_dir = os.environ.get("AMVISION_FFMPEG_BIN_DIR")
    if explicit_bin_dir:
        candidate_paths.append(Path(explicit_bin_dir).expanduser() / tool_file_name)

    release_tool_roots = [
        _APP_ROOT_DIR.parent / "tools" / "ffmpeg",
        _APP_ROOT_DIR / "release" / "full" / "tools" / "ffmpeg",
    ]
    for release_tool_root in release_tool_roots:
        candidate_paths.extend(
            [
                release_tool_root / "bin" / tool_file_name,
                release_tool_root / platform_dir_name / "bin" / tool_file_name,
                release_tool_root / platform_dir_name / tool_file_name,
                release_tool_root / tool_file_name,
            ]
        )

    repo_tool_root = _APP_ROOT_DIR / "runtimes" / "third_party" / "ffmpeg"
    candidate_paths.extend(
        [
            repo_tool_root / platform_dir_name / "bin" / tool_file_name,
            repo_tool_root / platform_dir_name / tool_file_name,
        ]
    )

    normalized_candidates: list[Path] = []
    seen_candidates: set[str] = set()
    for candidate_path in candidate_paths:
        normalized_candidate = candidate_path.expanduser()
        normalized_key = str(normalized_candidate)
        if normalized_key in seen_candidates:
            continue
        seen_candidates.add(normalized_key)
        normalized_candidates.append(normalized_candidate)
    return normalized_candidates


def _tool_file_name(tool_name: str) -> str:
    """返回当前平台对应的工具文件名。"""

    if sys.platform.startswith("win"):
        return f"{tool_name}.exe"
    return tool_name


def _infer_video_file_extension_from_media_type(media_type: str) -> str:
    """根据媒体类型推断视频文件扩展名。"""

    guessed_extension = mimetypes.guess_extension(media_type.strip()) if isinstance(media_type, str) else None
    if isinstance(guessed_extension, str) and guessed_extension:
        return guessed_extension
    return ".mp4"


def _run_video_tool_command(
    command: list[str],
    *,
    error_title: str,
    details: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    """运行视频工具命令。"""

    completed_process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed_process.returncode != 0:
        raise InvalidRequestError(
            error_title,
            details={
                **details,
                "command": command,
                "returncode": completed_process.returncode,
                "stdout": completed_process.stdout.strip(),
                "stderr": completed_process.stderr.strip(),
            },
        )
    return completed_process


def _parse_ffprobe_frame_rate(raw_value: object) -> float:
    """解析 ffprobe 的帧率字段。"""

    if not isinstance(raw_value, str):
        return 0.0
    normalized_value = raw_value.strip()
    if not normalized_value or normalized_value == "0/0":
        return 0.0
    if "/" not in normalized_value:
        normalized_number = _normalize_optional_non_negative_number(normalized_value)
        return float(normalized_number or 0.0)
    numerator_text, denominator_text = normalized_value.split("/", 1)
    numerator = _normalize_optional_non_negative_number(numerator_text)
    denominator = _normalize_optional_non_negative_number(denominator_text)
    if numerator is None or denominator is None or denominator <= 0:
        return 0.0
    return float(numerator / denominator)


def _normalize_optional_non_negative_int(value: object) -> int | None:
    """规范化可选非负整数。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        normalized_value = int(value)
        return normalized_value if normalized_value >= 0 else None
    if isinstance(value, str):
        normalized_value = value.strip()
        if not normalized_value:
            return None
        try:
            parsed_value = int(float(normalized_value))
        except ValueError:
            return None
        return parsed_value if parsed_value >= 0 else None
    return None


def _normalize_optional_non_negative_number(value: object) -> float | None:
    """规范化可选非负数。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        normalized_value = float(value)
        return normalized_value if normalized_value >= 0 else None
    if isinstance(value, str):
        normalized_value = value.strip()
        if not normalized_value:
            return None
        try:
            parsed_value = float(normalized_value)
        except ValueError:
            return None
        return parsed_value if parsed_value >= 0 else None
    return None


def _normalize_optional_text(value: object) -> str | None:
    """规范化可选文本字段。"""

    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None
