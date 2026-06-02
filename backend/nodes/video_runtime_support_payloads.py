"""视频 payload、存储与响应体 helper。"""

from __future__ import annotations

from pathlib import Path

from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.nodes.video_runtime_support_tools import (
    infer_video_file_extension_from_media_type,
    infer_video_media_type,
    normalize_optional_non_negative_int,
    normalize_optional_non_negative_number,
    normalize_optional_text,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.execution_cleanup import register_dataset_storage_object_cleanup
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.preview_display_outputs import (
    build_preview_run_artifact_object_key,
    read_preview_run_id,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


VIDEO_TRANSPORT_LOCAL_PATH = "local-path"
VIDEO_TRANSPORT_STORAGE = "storage"
RESPONSE_VIDEO_TRANSPORT_STORAGE_REF = "storage-ref"


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
        normalized_value = normalize_optional_non_negative_int(normalized_payload.get(field_name))
        if normalized_value is None:
            normalized_payload.pop(field_name, None)
        else:
            normalized_payload[field_name] = normalized_value
    for field_name in ("fps", "duration_ms"):
        normalized_value = normalize_optional_non_negative_number(normalized_payload.get(field_name))
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
    source_object_key = normalize_optional_text(normalized_source_payload.get("object_key"))
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

    source_object_key = normalize_optional_text(normalized_source_payload.get("object_key"))
    media_type = str(normalized_source_payload.get("media_type") or "video/mp4")
    preview_run_id = read_preview_run_id(request.execution_metadata)
    if preview_run_id is not None:
        return build_preview_run_artifact_object_key(
            preview_run_id=preview_run_id,
            node_id=request.node_id,
            artifact_name=variant_name,
            media_type=media_type,
        )

    output_extension = infer_video_file_extension_from_media_type(media_type)
    if source_object_key is not None:
        source_reference_payload: dict[str, object] | None = {
            "transport_kind": VIDEO_TRANSPORT_STORAGE,
            "object_key": source_object_key,
            "media_type": media_type,
        }
    else:
        local_path = normalize_optional_text(normalized_source_payload.get("local_path")) or "video.mp4"
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
    normalized_object_key = normalize_optional_text(object_key)
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
