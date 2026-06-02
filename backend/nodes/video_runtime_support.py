"""视频 workflow 节点共享 helper。"""

from __future__ import annotations

import mimetypes
from pathlib import Path

import cv2

from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


VIDEO_TRANSPORT_LOCAL_PATH = "local-path"
VIDEO_TRANSPORT_STORAGE = "storage"


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


def _normalize_optional_non_negative_int(value: object) -> int | None:
    """规范化可选非负整数。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        normalized_value = int(value)
        return normalized_value if normalized_value >= 0 else None
    return None


def _normalize_optional_non_negative_number(value: object) -> float | None:
    """规范化可选非负数。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        normalized_value = float(value)
        return normalized_value if normalized_value >= 0 else None
    return None
