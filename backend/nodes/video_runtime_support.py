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

from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


VIDEO_TRANSPORT_LOCAL_PATH = "local-path"
VIDEO_TRANSPORT_STORAGE = "storage"
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
