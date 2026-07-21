"""节点运行时的图片与文件 helper。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import mimetypes
from pathlib import PurePosixPath
from threading import Lock, RLock
from typing import Any
from uuid import uuid4

from backend.contracts.buffers import BufferRef, FrameRef
from backend.service.application.images.image_matrix import (
    IMAGE_MEDIA_TYPE_RAW,
    apply_raw_ref_metadata,
    build_raw_bgr24_payload_fields,
    decode_image_bytes_to_matrix,
    encode_matrix_to_image_bytes,
    is_raw_bgr24_payload,
    normalize_image_payload_metadata,
    prepare_matrix_for_raw_bgr24,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.execution_cleanup import register_dataset_storage_object_cleanup
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


IMAGE_TRANSPORT_MEMORY = "memory"
IMAGE_TRANSPORT_STORAGE = "storage"
IMAGE_TRANSPORT_BUFFER = "buffer"
IMAGE_TRANSPORT_FRAME = "frame"
RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64 = "inline-base64"
RESPONSE_IMAGE_TRANSPORT_STORAGE_REF = "storage-ref"
PREVIEW_DISPLAY_HIGH_RESOLUTION_PIXELS = 1920 * 1080
PREVIEW_DISPLAY_HIGH_RESOLUTION_LONG_EDGE = 1920
PREVIEW_DISPLAY_MAX_LONG_EDGE = 1920
PREVIEW_DISPLAY_MEDIA_TYPE = "image/jpeg"
PREVIEW_DISPLAY_EXTENSION = ".jpg"
PreviewLoadedImage = tuple[dict[str, object], Any, int, int]


@dataclass(frozen=True)
class ExecutionImageEntry:
    """描述 execution image registry 中的一张图片。

    字段：
    - image_handle：当前执行范围内的图片句柄。
    - content：图片 bytes；编码图片保存编码后 bytes，raw 图片可为空并直接保存 matrix。
    - matrix：OpenCV / NumPy 图片矩阵；raw BGR24 内部流转优先使用该字段。
    - media_type：图片媒体类型。
    - width：图片宽度。
    - height：图片高度。
    - byte_length：图片字节长度。
    - shape：raw 图片 shape。
    - dtype：raw 数据类型。
    - layout：raw 数据布局。
    - pixel_format：raw 像素格式。
    - created_by_node_id：创建该图片的节点 id。
    """

    image_handle: str
    content: bytes | None
    media_type: str
    matrix: Any | None = None
    width: int | None = None
    height: int | None = None
    byte_length: int = 0
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None
    created_by_node_id: str | None = None


@dataclass(frozen=True)
class ResolvedImageInput:
    """描述一次图片输入解析后的统一视图。

    字段：
    - payload：规范化后的 image-ref payload。
    - transport_kind：图片传输方式，支持 memory、storage、buffer 或 frame。
    - media_type：图片媒体类型。
    - width：图片宽度。
    - height：图片高度。
    - object_key：storage 模式下的本地 object key。
    - image_handle：memory 模式下的执行期图片句柄。
    - buffer_ref：buffer 模式下的 LocalBufferBroker 引用。
    - frame_ref：frame 模式下的 LocalBufferBroker 帧引用。
    - shape：raw 图片 shape。
    - dtype：raw 数据类型。
    - layout：raw 数据布局。
    - pixel_format：raw 像素格式。
    """

    payload: dict[str, object]
    transport_kind: str
    media_type: str
    width: int | None = None
    height: int | None = None
    object_key: str | None = None
    image_handle: str | None = None
    buffer_ref: BufferRef | None = None
    frame_ref: FrameRef | None = None
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None


class ExecutionImageRegistry:
    """在单次 workflow 执行范围内管理内存图片引用。"""

    def __init__(self) -> None:
        """初始化空的 execution image registry。"""

        self._entries: dict[str, ExecutionImageEntry] = {}
        self._decoded_matrices: dict[str, Any] = {}
        self._decoded_matrix_locks: dict[str, Lock] = {}
        self._lock = RLock()

    def register_image_bytes(
        self,
        *,
        content: bytes,
        media_type: str,
        width: int | None = None,
        height: int | None = None,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        created_by_node_id: str | None = None,
    ) -> ExecutionImageEntry:
        """注册一张内存图片并返回稳定条目。

        参数：
        - content：图片编码后字节。
        - media_type：图片媒体类型。
        - width：图片宽度。
        - height：图片高度。
        - shape：raw 图片 shape。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：raw 像素格式。
        - created_by_node_id：创建节点 id。

        返回：
        - ExecutionImageEntry：注册后的图片条目。
        """

        normalized_media_type = media_type.strip() if isinstance(media_type, str) else ""
        if not normalized_media_type:
            raise InvalidRequestError("execution image registry 要求 media_type 不能为空")
        if not isinstance(content, bytes) or not content:
            raise InvalidRequestError("execution image registry 要求 content 必须是非空 bytes")
        image_handle = f"img-{uuid4().hex}"
        entry = ExecutionImageEntry(
            image_handle=image_handle,
            content=content,
            media_type=normalized_media_type,
            width=_normalize_optional_dimension(width),
            height=_normalize_optional_dimension(height),
            byte_length=len(content),
            shape=tuple(int(item) for item in shape),
            dtype=_normalize_optional_text(dtype),
            layout=_normalize_optional_text(layout),
            pixel_format=_normalize_optional_text(pixel_format),
            created_by_node_id=_normalize_optional_text(created_by_node_id),
        )
        with self._lock:
            self._entries[image_handle] = entry
        return entry

    def register_image_matrix(
        self,
        *,
        matrix: Any,
        width: int,
        height: int,
        created_by_node_id: str | None = None,
    ) -> ExecutionImageEntry:
        """注册一张 raw BGR24 内存图片并返回稳定条目。"""

        image_handle = f"img-{uuid4().hex}"
        entry = ExecutionImageEntry(
            image_handle=image_handle,
            content=None,
            matrix=matrix,
            media_type=IMAGE_MEDIA_TYPE_RAW,
            width=_normalize_optional_dimension(width),
            height=_normalize_optional_dimension(height),
            byte_length=int(width) * int(height) * 3,
            shape=(int(height), int(width), 3),
            dtype="uint8",
            layout="HWC",
            pixel_format="bgr24",
            created_by_node_id=_normalize_optional_text(created_by_node_id),
        )
        with self._lock:
            self._entries[image_handle] = entry
        return entry

    def get_entry(self, image_handle: str) -> ExecutionImageEntry:
        """按句柄读取一张已注册的内存图片。

        参数：
        - image_handle：图片句柄。

        返回：
        - ExecutionImageEntry：对应的图片条目。
        """

        normalized_image_handle = image_handle.strip() if isinstance(image_handle, str) else ""
        if not normalized_image_handle:
            raise InvalidRequestError("execution image registry 要求 image_handle 不能为空")
        with self._lock:
            entry = self._entries.get(normalized_image_handle)
        if entry is None:
            raise InvalidRequestError(
                "execution image registry 中不存在指定图片句柄",
                details={"image_handle": normalized_image_handle},
            )
        return entry

    def read_bytes(self, image_handle: str) -> bytes:
        """按句柄读取已注册图片的编码后字节。

        参数：
        - image_handle：图片句柄。

        返回：
        - bytes：图片编码后字节。
        """

        entry = self.get_entry(image_handle)
        if entry.content is not None:
            return entry.content
        matrix = entry.matrix
        if matrix is None or not hasattr(matrix, "tobytes"):
            raise InvalidRequestError(
                "execution image registry 中的图片没有可读取的 bytes",
                details={"image_handle": entry.image_handle},
            )
        return matrix.tobytes()

    def read_matrix(self, image_handle: str) -> Any | None:
        """按句柄读取已注册图片矩阵；非 raw 图片返回 None。"""

        return self.get_entry(image_handle).matrix

    def get_or_decode_matrix(
        self,
        *,
        cache_key: str,
        decoder: Any,
    ) -> Any:
        """按输入引用和解码模式在单次 Workflow Run 内复用解码矩阵。

        同一张 storage/buffer/frame 图片可能同时供多个定位节点使用。这里按 key
        做 single-flight，避免大图被重复读取和解码，同时不把矩阵缓存扩展到 Run
        之外，防止长期 runtime 持有现场图片。
        """

        normalized_cache_key = cache_key.strip() if isinstance(cache_key, str) else ""
        if not normalized_cache_key:
            raise InvalidRequestError("execution image registry 解码缓存 key 不能为空")
        if not callable(decoder):
            raise InvalidRequestError("execution image registry decoder 必须可调用")
        with self._lock:
            cached_matrix = self._decoded_matrices.get(normalized_cache_key)
            if cached_matrix is not None:
                return cached_matrix
            decode_lock = self._decoded_matrix_locks.get(normalized_cache_key)
            if decode_lock is None:
                decode_lock = Lock()
                self._decoded_matrix_locks[normalized_cache_key] = decode_lock
        with decode_lock:
            with self._lock:
                cached_matrix = self._decoded_matrices.get(normalized_cache_key)
                if cached_matrix is not None:
                    return cached_matrix
            decoded_matrix = decoder()
            with self._lock:
                self._decoded_matrices[normalized_cache_key] = decoded_matrix
            return decoded_matrix

    def release(self, image_handle: str) -> None:
        """释放一张已注册的内存图片。

        参数：
        - image_handle：图片句柄。
        """

        normalized_image_handle = image_handle.strip() if isinstance(image_handle, str) else ""
        if normalized_image_handle:
            with self._lock:
                self._entries.pop(normalized_image_handle, None)

    def clear(self) -> None:
        """清空当前执行范围内的全部图片。"""

        with self._lock:
            self._entries.clear()
            self._decoded_matrices.clear()
            self._decoded_matrix_locks.clear()


def require_dataset_storage(request: WorkflowNodeExecutionRequest) -> LocalDatasetStorage:
    """从执行元数据中读取 LocalDatasetStorage。

    参数：
    - request：当前节点执行请求。

    返回：
    - LocalDatasetStorage：当前执行上下文绑定的文件存储服务。
    """

    dataset_storage = request.execution_metadata.get("dataset_storage")
    if not isinstance(dataset_storage, LocalDatasetStorage):
        raise ServiceConfigurationError(
            "当前节点执行缺少 LocalDatasetStorage 上下文",
            details={"node_id": request.node_id, "required_metadata": "dataset_storage"},
        )
    return dataset_storage


def require_execution_image_registry(request: WorkflowNodeExecutionRequest) -> ExecutionImageRegistry:
    """从执行元数据中读取 execution image registry。

    参数：
    - request：当前节点执行请求。

    返回：
    - ExecutionImageRegistry：当前执行上下文绑定的图片 registry。
    """

    image_registry = request.execution_metadata.get("execution_image_registry")
    if image_registry is None:
        image_registry = ExecutionImageRegistry()
        request.execution_metadata["execution_image_registry"] = image_registry
    if not isinstance(image_registry, ExecutionImageRegistry):
        raise ServiceConfigurationError(
            "当前节点执行缺少 ExecutionImageRegistry 上下文",
            details={"node_id": request.node_id, "required_metadata": "execution_image_registry"},
        )
    return image_registry


def require_image_payload(payload: object) -> dict[str, object]:
    """校验并规范化 image-ref payload。

    参数：
    - payload：待校验的输入 payload。

    返回：
    - dict[str, object]：标准化后的图片引用 payload。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("图片节点要求 image-ref payload 必须是对象")
    normalized_payload = dict(payload)
    transport_kind = normalized_payload.get("transport_kind")
    normalized_transport_kind = transport_kind.strip() if isinstance(transport_kind, str) else ""
    object_key = normalized_payload.get("object_key")
    image_handle = normalized_payload.get("image_handle")
    buffer_ref_value = normalized_payload.get("buffer_ref")
    frame_ref_value = normalized_payload.get("frame_ref")

    if not normalized_transport_kind:
        if isinstance(object_key, str) and object_key.strip():
            normalized_transport_kind = IMAGE_TRANSPORT_STORAGE
        elif isinstance(image_handle, str) and image_handle.strip():
            normalized_transport_kind = IMAGE_TRANSPORT_MEMORY
        elif buffer_ref_value is not None:
            normalized_transport_kind = IMAGE_TRANSPORT_BUFFER
        elif frame_ref_value is not None:
            normalized_transport_kind = IMAGE_TRANSPORT_FRAME

    if normalized_transport_kind not in {
        IMAGE_TRANSPORT_MEMORY,
        IMAGE_TRANSPORT_STORAGE,
        IMAGE_TRANSPORT_BUFFER,
        IMAGE_TRANSPORT_FRAME,
    }:
        raise InvalidRequestError("image-ref payload 缺少有效 transport_kind")

    normalized_payload["transport_kind"] = normalized_transport_kind
    if normalized_transport_kind == IMAGE_TRANSPORT_STORAGE:
        if not isinstance(object_key, str) or not object_key.strip():
            raise InvalidRequestError("storage image-ref payload 缺少有效 object_key")
        normalized_payload["object_key"] = object_key.strip()
        normalized_payload.pop("image_handle", None)
        media_type = normalized_payload.get("media_type")
        if not isinstance(media_type, str) or not media_type.strip():
            normalized_payload["media_type"] = infer_media_type(normalized_payload["object_key"])
    elif normalized_transport_kind == IMAGE_TRANSPORT_MEMORY:
        if not isinstance(image_handle, str) or not image_handle.strip():
            raise InvalidRequestError("memory image-ref payload 缺少有效 image_handle")
        normalized_payload["image_handle"] = image_handle.strip()
        normalized_payload.pop("object_key", None)
        media_type = normalized_payload.get("media_type")
        if not isinstance(media_type, str) or not media_type.strip():
            raise InvalidRequestError("memory image-ref payload 缺少有效 media_type")
        normalized_payload["media_type"] = media_type.strip()
    elif normalized_transport_kind == IMAGE_TRANSPORT_BUFFER:
        buffer_ref = _require_buffer_ref_payload(buffer_ref_value)
        _apply_media_type_from_ref(
            normalized_payload,
            ref_media_type=buffer_ref.media_type,
            transport_kind=IMAGE_TRANSPORT_BUFFER,
        )
        apply_raw_ref_metadata(
            normalized_payload,
            shape=buffer_ref.shape,
            dtype=buffer_ref.dtype,
            layout=buffer_ref.layout,
            pixel_format=buffer_ref.pixel_format,
        )
        _apply_dimensions_from_ref_shape(
            normalized_payload,
            shape=buffer_ref.shape,
            layout=buffer_ref.layout,
        )
        normalized_payload["buffer_ref"] = buffer_ref.model_dump(mode="json")
        normalized_payload.pop("object_key", None)
        normalized_payload.pop("image_handle", None)
        normalized_payload.pop("frame_ref", None)
    else:
        frame_ref = _require_frame_ref_payload(frame_ref_value)
        _apply_media_type_from_ref(
            normalized_payload,
            ref_media_type=frame_ref.media_type,
            transport_kind=IMAGE_TRANSPORT_FRAME,
        )
        apply_raw_ref_metadata(
            normalized_payload,
            shape=frame_ref.shape,
            dtype=frame_ref.dtype,
            layout=frame_ref.layout,
            pixel_format=frame_ref.pixel_format,
        )
        _apply_dimensions_from_ref_shape(
            normalized_payload,
            shape=frame_ref.shape,
            layout=frame_ref.layout,
        )
        normalized_payload["frame_ref"] = frame_ref.model_dump(mode="json")
        normalized_payload.pop("object_key", None)
        normalized_payload.pop("image_handle", None)
        normalized_payload.pop("buffer_ref", None)

    normalized_width = _normalize_optional_dimension(normalized_payload.get("width"))
    normalized_height = _normalize_optional_dimension(normalized_payload.get("height"))
    if normalized_width is None:
        normalized_payload.pop("width", None)
    else:
        normalized_payload["width"] = normalized_width
    if normalized_height is None:
        normalized_payload.pop("height", None)
    else:
        normalized_payload["height"] = normalized_height
    metadata = normalize_image_payload_metadata(normalized_payload)
    if metadata.shape:
        normalized_payload["shape"] = [int(item) for item in metadata.shape]
    else:
        normalized_payload.pop("shape", None)
    if metadata.dtype is None:
        normalized_payload.pop("dtype", None)
    else:
        normalized_payload["dtype"] = metadata.dtype
    if metadata.layout is None:
        normalized_payload.pop("layout", None)
    else:
        normalized_payload["layout"] = metadata.layout
    if metadata.pixel_format is None:
        normalized_payload.pop("pixel_format", None)
    else:
        normalized_payload["pixel_format"] = metadata.pixel_format
    return normalized_payload


def _require_buffer_ref_payload(payload: object) -> BufferRef:
    """校验并返回 BufferRef。"""

    if isinstance(payload, BufferRef):
        return payload
    if not isinstance(payload, dict):
        raise InvalidRequestError("buffer image-ref payload 缺少有效 buffer_ref")
    try:
        return BufferRef.model_validate(payload)
    except ValueError as exc:
        raise InvalidRequestError(
            "buffer image-ref payload 缺少有效 buffer_ref",
            details={"error": str(exc)},
        ) from exc


def _require_frame_ref_payload(payload: object) -> FrameRef:
    """校验并返回 FrameRef。"""

    if isinstance(payload, FrameRef):
        return payload
    if not isinstance(payload, dict):
        raise InvalidRequestError("frame image-ref payload 缺少有效 frame_ref")
    try:
        return FrameRef.model_validate(payload)
    except ValueError as exc:
        raise InvalidRequestError(
            "frame image-ref payload 缺少有效 frame_ref",
            details={"error": str(exc)},
        ) from exc


def _apply_media_type_from_ref(
    payload: dict[str, object],
    *,
    ref_media_type: str,
    transport_kind: str,
) -> None:
    """按 BufferRef 或 FrameRef 统一 media_type。"""

    normalized_media_type = _normalize_optional_text(payload.get("media_type"))
    if normalized_media_type is not None and normalized_media_type != ref_media_type:
        raise InvalidRequestError(
            "image-ref payload media_type 与底层引用不一致",
            details={"transport_kind": transport_kind, "media_type": normalized_media_type},
        )
    payload["media_type"] = ref_media_type


def _apply_dimensions_from_ref_shape(
    payload: dict[str, object],
    *,
    shape: tuple[int, ...],
    layout: str | None,
) -> None:
    """在未显式提供宽高时尝试从 raw 图像 shape 推断。"""

    if payload.get("width") is not None or payload.get("height") is not None:
        return
    normalized_layout = layout.strip().upper() if isinstance(layout, str) else ""
    if normalized_layout == "HWC" and len(shape) >= 2:
        payload["height"] = shape[0]
        payload["width"] = shape[1]
    elif normalized_layout == "CHW" and len(shape) >= 3:
        payload["height"] = shape[1]
        payload["width"] = shape[2]


def resolve_image_reference(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
) -> ResolvedImageInput:
    """解析图片输入并返回统一轻量视图。

    参数：
    - request：当前节点执行请求。
    - input_name：要读取的输入端口名称。

    返回：
    - ResolvedImageInput：统一解析后的图片输入视图。
    """

    payload = require_image_payload(request.input_values.get(input_name))
    metadata = normalize_image_payload_metadata(payload)
    return ResolvedImageInput(
        payload=payload,
        transport_kind=str(payload["transport_kind"]),
        media_type=str(payload["media_type"]),
        width=_normalize_optional_dimension(payload.get("width")),
        height=_normalize_optional_dimension(payload.get("height")),
        object_key=_normalize_optional_text(payload.get("object_key")),
        image_handle=_normalize_optional_text(payload.get("image_handle")),
        buffer_ref=BufferRef.model_validate(payload["buffer_ref"])
        if payload.get("buffer_ref") is not None
        else None,
        frame_ref=FrameRef.model_validate(payload["frame_ref"])
        if payload.get("frame_ref") is not None
        else None,
        shape=metadata.shape,
        dtype=metadata.dtype,
        layout=metadata.layout,
        pixel_format=metadata.pixel_format,
    )


def resolve_image_input(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
) -> tuple[LocalDatasetStorage, dict[str, object], str]:
    """解析输入图片 payload，并返回对应 object key。

    参数：
    - request：当前节点执行请求。
    - input_name：要读取的输入端口名称。

    返回：
    - tuple[LocalDatasetStorage, dict[str, object], str]：文件存储、规范化 payload 和 object key。
    """

    dataset_storage = require_dataset_storage(request)
    resolved_image = resolve_image_reference(request, input_name=input_name)
    if resolved_image.transport_kind != IMAGE_TRANSPORT_STORAGE or resolved_image.object_key is None:
        raise InvalidRequestError(
            "当前节点尚未支持 memory image-ref payload，请改用双模式 helper",
            details={"node_id": request.node_id, "input_name": input_name},
        )
    object_key = resolved_image.object_key
    source_path = dataset_storage.resolve(object_key)
    if not source_path.is_file():
        raise InvalidRequestError(
            "图片节点引用的 object_key 不存在",
            details={"node_id": request.node_id, "object_key": object_key},
        )
    return dataset_storage, dict(resolved_image.payload), object_key


def load_image_bytes(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
) -> tuple[dict[str, object], bytes]:
    """按双模式规则读取图片编码后字节。

    参数：
    - request：当前节点执行请求。
    - input_name：要读取的输入端口名称。

    返回：
    - tuple[dict[str, object], bytes]：规范化 payload 与图片字节。
    """

    return load_image_bytes_from_payload(
        request,
        image_payload=request.input_values.get(input_name),
    )


def load_image_bytes_from_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: object,
) -> tuple[dict[str, object], bytes]:
    """按双模式规则读取任意 image-ref payload 对应的图片字节。

    参数：
    - request：当前节点执行请求。
    - image_payload：待读取的图片 payload。

    返回：
    - tuple[dict[str, object], bytes]：规范化 payload 与图片字节。
    """

    normalized_payload = require_image_payload(image_payload)
    metadata = normalize_image_payload_metadata(normalized_payload)
    resolved_image = ResolvedImageInput(
        payload=normalized_payload,
        transport_kind=str(normalized_payload["transport_kind"]),
        media_type=str(normalized_payload["media_type"]),
        width=_normalize_optional_dimension(normalized_payload.get("width")),
        height=_normalize_optional_dimension(normalized_payload.get("height")),
        object_key=_normalize_optional_text(normalized_payload.get("object_key")),
        image_handle=_normalize_optional_text(normalized_payload.get("image_handle")),
        buffer_ref=BufferRef.model_validate(normalized_payload["buffer_ref"])
        if normalized_payload.get("buffer_ref") is not None
        else None,
        frame_ref=FrameRef.model_validate(normalized_payload["frame_ref"])
        if normalized_payload.get("frame_ref") is not None
        else None,
        shape=metadata.shape,
        dtype=metadata.dtype,
        layout=metadata.layout,
        pixel_format=metadata.pixel_format,
    )
    if resolved_image.transport_kind == IMAGE_TRANSPORT_STORAGE:
        dataset_storage = require_dataset_storage(request)
        assert resolved_image.object_key is not None
        source_path = dataset_storage.resolve(resolved_image.object_key)
        if not source_path.is_file():
            raise InvalidRequestError(
                "图片节点引用的 object_key 不存在",
                details={"node_id": request.node_id, "object_key": resolved_image.object_key},
            )
        return dict(resolved_image.payload), source_path.read_bytes()

    if resolved_image.transport_kind == IMAGE_TRANSPORT_MEMORY:
        image_registry = require_execution_image_registry(request)
        assert resolved_image.image_handle is not None
        return dict(resolved_image.payload), image_registry.read_bytes(resolved_image.image_handle)

    local_buffer_reader = require_local_buffer_reader(request)
    if resolved_image.transport_kind == IMAGE_TRANSPORT_BUFFER:
        assert resolved_image.buffer_ref is not None
        return dict(resolved_image.payload), local_buffer_reader.read_buffer_ref(resolved_image.buffer_ref)
    if resolved_image.transport_kind == IMAGE_TRANSPORT_FRAME:
        assert resolved_image.frame_ref is not None
        return dict(resolved_image.payload), local_buffer_reader.read_frame_ref(resolved_image.frame_ref)
    raise InvalidRequestError(
        "image-ref payload 使用了不支持的 transport_kind",
        details={"transport_kind": resolved_image.transport_kind},
    )


def require_local_buffer_reader(request: WorkflowNodeExecutionRequest) -> object:
    """从执行元数据中读取 LocalBufferBroker reader。

    参数：
    - request：当前节点执行请求。

    返回：
    - object：实现 read_buffer_ref 与 read_frame_ref 的 reader。
    """

    local_buffer_reader = request.execution_metadata.get("local_buffer_reader")
    if local_buffer_reader is None:
        raise ServiceConfigurationError(
            "当前节点执行缺少 LocalBufferBroker reader 上下文",
            details={"node_id": request.node_id, "required_metadata": "local_buffer_reader"},
        )
    if not callable(getattr(local_buffer_reader, "read_buffer_ref", None)):
        raise ServiceConfigurationError(
            "LocalBufferBroker reader 缺少 read_buffer_ref 方法",
            details={"node_id": request.node_id},
        )
    if not callable(getattr(local_buffer_reader, "read_frame_ref", None)):
        raise ServiceConfigurationError(
            "LocalBufferBroker reader 缺少 read_frame_ref 方法",
            details={"node_id": request.node_id},
        )
    return local_buffer_reader


def build_runtime_image_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    source_object_key: str,
    variant_name: str,
    output_extension: str | None = None,
) -> str:
    """基于当前执行上下文生成新的图片 object key。

    参数：
    - request：当前节点执行请求。
    - source_object_key：源图片 object key。
    - variant_name：当前输出变体名称。
    - output_extension：目标文件扩展名；未提供时沿用源扩展名。

    返回：
    - str：生成后的目标 object key。
    """

    workflow_run_id = str(request.execution_metadata.get("workflow_run_id") or "default-run")
    source_path = PurePosixPath(source_object_key)
    source_stem = source_path.stem or "image"
    source_suffix = output_extension or source_path.suffix or ".png"
    normalized_variant_name = variant_name.strip().replace(" ", "-") or "output"
    return (
        f"workflows/runtime/{workflow_run_id}/{request.node_id}/"
        f"{source_stem}-{normalized_variant_name}{source_suffix}"
    )


def build_memory_image_payload(
    *,
    image_handle: str,
    media_type: str,
    width: int | None = None,
    height: int | None = None,
    shape: tuple[int, ...] = (),
    dtype: str | None = None,
    layout: str | None = None,
    pixel_format: str | None = None,
) -> dict[str, object]:
    """构建 memory 模式 image-ref payload。

    参数：
    - image_handle：执行期图片句柄。
    - media_type：图片媒体类型。
    - width：图片宽度。
    - height：图片高度。
    - shape：raw 图片 shape。
    - dtype：raw 数据类型。
    - layout：raw 数据布局。
    - pixel_format：raw 像素格式。

    返回：
    - dict[str, object]：memory 模式图片引用。
    """

    normalized_image_handle = image_handle.strip() if isinstance(image_handle, str) else ""
    normalized_media_type = media_type.strip() if isinstance(media_type, str) else ""
    if not normalized_image_handle:
        raise InvalidRequestError("memory image-ref payload 要求 image_handle 不能为空")
    if not normalized_media_type:
        raise InvalidRequestError("memory image-ref payload 要求 media_type 不能为空")
    payload: dict[str, object] = {
        "transport_kind": IMAGE_TRANSPORT_MEMORY,
        "image_handle": normalized_image_handle,
        "media_type": normalized_media_type,
    }
    normalized_width = _normalize_optional_dimension(width)
    normalized_height = _normalize_optional_dimension(height)
    if normalized_width is not None:
        payload["width"] = normalized_width
    if normalized_height is not None:
        payload["height"] = normalized_height
    apply_raw_ref_metadata(
        payload,
        shape=tuple(int(item) for item in shape),
        dtype=dtype,
        layout=layout,
        pixel_format=pixel_format,
    )
    return payload


def build_storage_image_payload(
    *,
    object_key: str,
    source_payload: dict[str, object] | None = None,
    width: int | None = None,
    height: int | None = None,
    media_type: str | None = None,
) -> dict[str, object]:
    """构建 storage 模式 image-ref payload。

    参数：
    - object_key：目标图片 object key。
    - source_payload：可选源图片 payload。
    - width：图片宽度。
    - height：图片高度。
    - media_type：图片媒体类型。

    返回：
    - dict[str, object]：storage 模式图片引用。
    """

    normalized_object_key = object_key.strip() if isinstance(object_key, str) else ""
    if not normalized_object_key:
        raise InvalidRequestError("storage image-ref payload 要求 object_key 不能为空")

    base_payload = require_image_payload(source_payload) if source_payload is not None else {}
    resolved_width = width if width is not None else base_payload.get("width")
    resolved_height = height if height is not None else base_payload.get("height")
    resolved_media_type = media_type or _normalize_optional_text(base_payload.get("media_type"))

    image_payload: dict[str, object] = {
        "transport_kind": IMAGE_TRANSPORT_STORAGE,
        "object_key": normalized_object_key,
        "media_type": resolved_media_type or infer_media_type(normalized_object_key),
    }
    normalized_width = _normalize_optional_dimension(resolved_width)
    normalized_height = _normalize_optional_dimension(resolved_height)
    if normalized_width is not None:
        image_payload["width"] = normalized_width
    if normalized_height is not None:
        image_payload["height"] = normalized_height
    return image_payload


def build_image_payload(
    *,
    object_key: str,
    source_payload: dict[str, object],
    width: int | None = None,
    height: int | None = None,
    media_type: str | None = None,
) -> dict[str, object]:
    """基于源图片 payload 生成新的 image-ref payload。

    参数：
    - object_key：目标图片 object key。
    - source_payload：源图片 payload。
    - width：可选宽度覆盖值。
    - height：可选高度覆盖值。
    - media_type：可选媒体类型覆盖值。

    返回：
    - dict[str, object]：新的 image-ref payload。
    """

    return build_storage_image_payload(
        object_key=object_key,
        source_payload=source_payload,
        width=width,
        height=height,
        media_type=media_type,
    )


def register_image_bytes(
    request: WorkflowNodeExecutionRequest,
    *,
    content: bytes,
    media_type: str,
    width: int | None = None,
    height: int | None = None,
    shape: tuple[int, ...] = (),
    dtype: str | None = None,
    layout: str | None = None,
    pixel_format: str | None = None,
    created_by_node_id: str | None = None,
) -> dict[str, object]:
    """把图片字节注册到 execution image registry，并返回 memory payload。

    参数：
    - request：当前节点执行请求。
    - content：图片编码后字节。
    - media_type：图片媒体类型。
    - width：图片宽度。
    - height：图片高度。
    - shape：raw 图片 shape。
    - dtype：raw 数据类型。
    - layout：raw 数据布局。
    - pixel_format：raw 像素格式。
    - created_by_node_id：创建节点 id。

    返回：
    - dict[str, object]：memory 模式图片引用。
    """

    image_registry = require_execution_image_registry(request)
    image_entry = image_registry.register_image_bytes(
        content=content,
        media_type=media_type,
        width=width,
        height=height,
        shape=shape,
        dtype=dtype,
        layout=layout,
        pixel_format=pixel_format,
        created_by_node_id=created_by_node_id or request.node_id,
    )
    return build_memory_image_payload(
        image_handle=image_entry.image_handle,
        media_type=image_entry.media_type,
        width=image_entry.width,
        height=image_entry.height,
        shape=image_entry.shape,
        dtype=image_entry.dtype,
        layout=image_entry.layout,
        pixel_format=image_entry.pixel_format,
    )


def register_image_matrix(
    request: WorkflowNodeExecutionRequest,
    *,
    image_matrix: Any,
    created_by_node_id: str | None = None,
) -> dict[str, object]:
    """把 OpenCV matrix 以 raw BGR24 注册到 execution image registry。

    参数：
    - request：当前节点执行请求。
    - image_matrix：OpenCV 图片矩阵。
    - created_by_node_id：创建节点 id。

    返回：
    - dict[str, object]：memory 模式 raw BGR24 图片引用。
    """

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    normalized_matrix = prepare_matrix_for_raw_bgr24(
        cv2_module=cv2,
        np_module=np,
        image_matrix=image_matrix,
    )
    image_registry = require_execution_image_registry(request)
    height, width = normalized_matrix.shape[:2]
    image_entry = image_registry.register_image_matrix(
        matrix=normalized_matrix,
        width=int(width),
        height=int(height),
        created_by_node_id=created_by_node_id or request.node_id,
    )
    raw_fields = build_raw_bgr24_payload_fields(width=int(width), height=int(height))
    return build_memory_image_payload(
        image_handle=image_entry.image_handle,
        media_type=str(raw_fields["media_type"]),
        width=int(raw_fields["width"]),
        height=int(raw_fields["height"]),
        shape=tuple(int(item) for item in raw_fields["shape"]),
        dtype=str(raw_fields["dtype"]),
        layout=str(raw_fields["layout"]),
        pixel_format=str(raw_fields["pixel_format"]),
    )


def load_image_matrix(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
    cv2_module: Any,
    np_module: Any,
    imdecode_flags: int | None = None,
    copy_raw: bool = False,
) -> tuple[dict[str, object], Any]:
    """读取 image-ref 并返回 OpenCV matrix。"""

    return load_image_matrix_from_payload(
        request,
        image_payload=request.input_values.get(input_name),
        cv2_module=cv2_module,
        np_module=np_module,
        imdecode_flags=imdecode_flags,
        copy_raw=copy_raw,
    )


def load_image_matrix_from_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: object,
    cv2_module: Any,
    np_module: Any,
    imdecode_flags: int | None = None,
    copy_raw: bool = False,
) -> tuple[dict[str, object], Any]:
    """读取任意 image-ref payload 并转换为 OpenCV matrix。"""

    normalized_payload = require_image_payload(image_payload)
    if normalized_payload.get("transport_kind") == IMAGE_TRANSPORT_MEMORY:
        image_handle = _normalize_optional_text(normalized_payload.get("image_handle"))
        if image_handle is not None and is_raw_bgr24_payload(normalized_payload):
            image_registry = require_execution_image_registry(request)
            matrix = image_registry.read_matrix(image_handle)
            if matrix is not None:
                matrix = prepare_matrix_for_raw_bgr24(
                    cv2_module=cv2_module,
                    np_module=np_module,
                    image_matrix=matrix,
                    copy_matrix=copy_raw,
                )
                if imdecode_flags == getattr(cv2_module, "IMREAD_GRAYSCALE", 0):
                    matrix = cv2_module.cvtColor(matrix, cv2_module.COLOR_BGR2GRAY)
                return normalized_payload, matrix
    image_registry = require_execution_image_registry(request)
    decode_cache_key = _build_decoded_matrix_cache_key(
        normalized_payload,
        imdecode_flags=imdecode_flags,
    )

    def decode_matrix() -> Any:
        """只在当前输入首次使用时读取并解码图片。"""

        _, image_bytes = load_image_bytes_from_payload(
            request,
            image_payload=normalized_payload,
        )
        return decode_image_bytes_to_matrix(
            cv2_module=cv2_module,
            np_module=np_module,
            image_bytes=image_bytes,
            image_payload=normalized_payload,
            imdecode_flags=imdecode_flags,
            error_message="图片节点无法读取输入图片",
            copy_raw=False,
        )

    matrix = image_registry.get_or_decode_matrix(
        cache_key=decode_cache_key,
        decoder=decode_matrix,
    )
    return normalized_payload, matrix.copy() if copy_raw else matrix


def _build_decoded_matrix_cache_key(
    image_payload: dict[str, object],
    *,
    imdecode_flags: int | None,
) -> str:
    """为单次执行中的稳定图片引用构造解码缓存 key。"""

    return json.dumps(
        {
            "image_payload": image_payload,
            "imdecode_flags": imdecode_flags,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def build_response_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: object,
    response_transport_mode: str = RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64,
    object_key: str | None = None,
    variant_name: str = "response-image",
    overwrite: bool = True,
) -> dict[str, object]:
    """把内部 image-ref payload 转换为对外 JSON 安全的响应图片结构。

    参数：
    - request：当前节点执行请求。
    - image_payload：内部 image-ref payload。
    - response_transport_mode：响应传输方式，支持 inline-base64 或 storage-ref。
    - object_key：可选目标 object key，仅在 storage-ref 模式下使用。
    - variant_name：自动生成目标 object key 时使用的变体名称。
    - overwrite：storage-ref 模式下是否允许覆盖目标文件。

    返回：
    - dict[str, object]：对外响应使用的稳定图片结构。
    """

    normalized_mode = _normalize_response_transport_mode(response_transport_mode)
    original_image_payload = require_image_payload(image_payload)
    source_was_raw = _is_raw_image_payload(original_image_payload)
    original_object_key = _normalize_optional_text(original_image_payload.get("object_key"))
    if (
        normalized_mode == RESPONSE_IMAGE_TRANSPORT_STORAGE_REF
        and original_image_payload["transport_kind"] == IMAGE_TRANSPORT_STORAGE
        and object_key is None
        and not source_was_raw
        and original_object_key is not None
    ):
        response_image: dict[str, object] = {
            "transport_kind": normalized_mode,
            "media_type": str(original_image_payload["media_type"]),
            "object_key": original_object_key,
        }
        normalized_width = _normalize_optional_dimension(original_image_payload.get("width"))
        normalized_height = _normalize_optional_dimension(original_image_payload.get("height"))
        if normalized_width is not None:
            response_image["width"] = normalized_width
        if normalized_height is not None:
            response_image["height"] = normalized_height
        return response_image

    normalized_image_payload, image_bytes = _load_json_safe_image_bytes(
        request,
        image_payload=original_image_payload,
    )
    response_image: dict[str, object] = {
        "transport_kind": normalized_mode,
        "media_type": str(normalized_image_payload["media_type"]),
    }
    normalized_width = _normalize_optional_dimension(normalized_image_payload.get("width"))
    normalized_height = _normalize_optional_dimension(normalized_image_payload.get("height"))
    if normalized_width is not None:
        response_image["width"] = normalized_width
    if normalized_height is not None:
        response_image["height"] = normalized_height

    if normalized_mode == RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64:
        response_image["image_base64"] = base64.b64encode(image_bytes).decode("ascii")
        return response_image

    if (
        normalized_image_payload["transport_kind"] == IMAGE_TRANSPORT_STORAGE
        and object_key is None
        and not source_was_raw
    ):
        stored_payload = build_storage_image_payload(
            object_key=str(normalized_image_payload["object_key"]),
            source_payload=normalized_image_payload,
        )
    else:
        stored_payload = copy_image_payload(
            request,
            source_payload=original_image_payload,
            object_key=object_key,
            overwrite=overwrite,
            variant_name=variant_name,
        )
    response_image["object_key"] = str(stored_payload["object_key"])
    return response_image


def build_preview_response_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: object,
    response_transport_mode: str = RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64,
    object_key: str | None = None,
    display_object_key: str | None = None,
    variant_name: str = "preview-image",
    overwrite: bool = True,
) -> dict[str, object]:
    """构建前端 Preview 使用的 source/display 双层图片结构。

    source_image 始终表示原图坐标空间，交互式取参面板必须使用它；
    display_image 只服务节点卡片和 gallery 缩略预览，高分辨率图片才会降采样。
    """

    normalized_mode = _normalize_response_transport_mode(response_transport_mode)
    original_image_payload = require_image_payload(image_payload)
    source_width, source_height = _read_payload_dimensions(original_image_payload)
    loaded_image: PreviewLoadedImage | None = None
    if source_width is None or source_height is None:
        loaded_image = _load_preview_image_matrix(
            request,
            image_payload=original_image_payload,
        )
        _, _, loaded_width, loaded_height = loaded_image
        source_width = loaded_width if loaded_width > 0 else None
        source_height = loaded_height if loaded_height > 0 else None
    high_resolution = _is_high_resolution_preview_image(source_width, source_height)
    source_mode = normalized_mode
    if (
        high_resolution
        and normalized_mode == RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64
        and object_key is not None
    ):
        source_mode = RESPONSE_IMAGE_TRANSPORT_STORAGE_REF

    source_image = build_response_image_payload(
        request,
        image_payload=original_image_payload,
        response_transport_mode=source_mode,
        object_key=object_key,
        variant_name=variant_name,
        overwrite=overwrite,
    )
    source_width, source_height = _read_payload_dimensions(source_image, fallback=(source_width, source_height))
    display_image = source_image
    display_scale = 1.0
    if _is_high_resolution_preview_image(source_width, source_height):
        display_image, detected_source_width, detected_source_height, display_scale = _build_resized_preview_display_image(
            request,
            image_payload=original_image_payload,
            source_image=source_image,
            response_transport_mode=normalized_mode,
            object_key=display_object_key,
            variant_name=f"{variant_name}-display",
            loaded_image=loaded_image,
        )
        source_width = detected_source_width
        source_height = detected_source_height

    display_width, display_height = _read_payload_dimensions(display_image)
    response_image = dict(display_image)
    response_image["source_image"] = dict(source_image)
    response_image["display_image"] = dict(display_image)
    if source_width is not None:
        response_image["source_width"] = int(source_width)
    if source_height is not None:
        response_image["source_height"] = int(source_height)
    if display_width is not None:
        response_image["display_width"] = int(display_width)
    if display_height is not None:
        response_image["display_height"] = int(display_height)
    response_image["display_scale"] = round(float(display_scale), 8)
    response_image["preview_image_kind"] = "display" if display_image != source_image else "source"
    return response_image


def _build_resized_preview_display_image(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: dict[str, object],
    source_image: dict[str, object],
    response_transport_mode: str,
    object_key: str | None,
    variant_name: str,
    loaded_image: PreviewLoadedImage | None = None,
) -> tuple[dict[str, object], int | None, int | None, float]:
    """为节点卡片构建高分辨率图片的 display 版本。"""

    import cv2  # noqa: PLC0415

    if loaded_image is None:
        normalized_payload, image_matrix, source_width, source_height = _load_preview_image_matrix(
            request,
            image_payload=image_payload,
        )
    else:
        normalized_payload, image_matrix, source_width, source_height = loaded_image
    if source_width <= 0 or source_height <= 0:
        return dict(source_image), None, None, 1.0
    scale = min(1.0, PREVIEW_DISPLAY_MAX_LONG_EDGE / float(max(source_width, source_height)))
    if scale >= 1.0:
        return dict(source_image), source_width, source_height, 1.0

    display_width = max(1, int(round(source_width * scale)))
    display_height = max(1, int(round(source_height * scale)))
    display_matrix = cv2.resize(
        image_matrix,
        (display_width, display_height),
        interpolation=cv2.INTER_AREA,
    )
    display_bytes = encode_matrix_to_image_bytes(
        cv2_module=cv2,
        image_matrix=display_matrix,
        extension=PREVIEW_DISPLAY_EXTENSION,
        error_message="Preview display 图片无法编码",
    )
    if response_transport_mode == RESPONSE_IMAGE_TRANSPORT_STORAGE_REF and object_key is not None:
        stored_payload = write_image_bytes(
            request,
            source_payload=normalized_payload,
            content=display_bytes,
            object_key=object_key,
            variant_name=variant_name,
            output_extension=PREVIEW_DISPLAY_EXTENSION,
            width=display_width,
            height=display_height,
            media_type=PREVIEW_DISPLAY_MEDIA_TYPE,
        )
        display_image: dict[str, object] = {
            "transport_kind": RESPONSE_IMAGE_TRANSPORT_STORAGE_REF,
            "media_type": PREVIEW_DISPLAY_MEDIA_TYPE,
            "object_key": str(stored_payload["object_key"]),
            "width": display_width,
            "height": display_height,
        }
        return display_image, source_width, source_height, scale

    display_image = {
        "transport_kind": RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64,
        "media_type": PREVIEW_DISPLAY_MEDIA_TYPE,
        "image_base64": base64.b64encode(display_bytes).decode("ascii"),
        "width": display_width,
        "height": display_height,
    }
    return display_image, source_width, source_height, scale


def _load_preview_image_matrix(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: dict[str, object],
) -> PreviewLoadedImage:
    """读取 Preview helper 专用图片矩阵，避免高分辨率预览重复解码。"""

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    normalized_payload, image_matrix = load_image_matrix_from_payload(
        request,
        image_payload=image_payload,
        cv2_module=cv2,
        np_module=np,
    )
    if image_matrix.ndim < 2:
        return normalized_payload, image_matrix, 0, 0
    return normalized_payload, image_matrix, int(image_matrix.shape[1]), int(image_matrix.shape[0])


def copy_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    source_payload: dict[str, object],
    object_key: str | None,
    overwrite: bool,
    variant_name: str,
) -> dict[str, object]:
    """复制图片到目标 object key，并返回新的 image-ref payload。

    参数：
    - request：当前节点执行请求。
    - source_payload：源图片 payload。
    - object_key：目标 object key；为空时自动生成。
    - overwrite：目标已存在时是否允许覆盖。
    - variant_name：自动生成 object key 时使用的变体名称。

    返回：
    - dict[str, object]：复制后的 image-ref payload。
    """

    dataset_storage = require_dataset_storage(request)
    normalized_source_payload = require_image_payload(source_payload)
    source_object_key = _normalize_optional_text(normalized_source_payload.get("object_key"))
    target_object_key = object_key or _build_default_target_object_key(
        request,
        normalized_source_payload=normalized_source_payload,
        variant_name=variant_name,
    )
    target_path = dataset_storage.resolve(target_object_key)
    if target_path.exists() and not overwrite and target_object_key != source_object_key:
        raise InvalidRequestError(
            "图片保存目标已存在，且当前节点未允许覆盖",
            details={"node_id": request.node_id, "object_key": target_object_key},
        )
    if _is_raw_image_payload(normalized_source_payload):
        json_safe_payload, image_bytes = _load_json_safe_image_bytes(
            request,
            image_payload=normalized_source_payload,
            target_object_key=target_object_key,
        )
        dataset_storage.write_bytes(target_object_key, image_bytes)
        normalized_source_payload = json_safe_payload
    elif normalized_source_payload["transport_kind"] == IMAGE_TRANSPORT_STORAGE and source_object_key is not None:
        if target_object_key != source_object_key:
            dataset_storage.copy_relative_file(source_object_key, target_object_key)
    else:
        _, image_bytes = load_image_bytes_from_payload(request, image_payload=normalized_source_payload)
        dataset_storage.write_bytes(target_object_key, image_bytes)
    _register_temporary_runtime_object_cleanup(
        request,
        object_key=target_object_key,
        was_generated=object_key is None,
    )
    return build_storage_image_payload(
        object_key=target_object_key,
        source_payload=normalized_source_payload,
    )


def write_image_bytes(
    request: WorkflowNodeExecutionRequest,
    *,
    source_payload: dict[str, object],
    content: bytes,
    object_key: str | None,
    variant_name: str,
    output_extension: str,
    width: int | None,
    height: int | None,
    media_type: str | None = None,
) -> dict[str, object]:
    """把图片字节写入文件存储，并返回新的 image-ref payload。

    参数：
    - request：当前节点执行请求。
    - source_payload：源图片 payload。
    - content：要写入的图片字节。
    - object_key：目标 object key；为空时自动生成。
    - variant_name：自动生成 object key 时使用的变体名称。
    - output_extension：目标图片扩展名。
    - width：输出宽度。
    - height：输出高度。
    - media_type：可选媒体类型。

    返回：
    - dict[str, object]：写入后的 image-ref payload。
    """

    dataset_storage = require_dataset_storage(request)
    normalized_source_payload = require_image_payload(source_payload)
    target_object_key = object_key or _build_default_target_object_key(
        request,
        normalized_source_payload=normalized_source_payload,
        variant_name=variant_name,
        output_extension=output_extension,
    )
    dataset_storage.write_bytes(target_object_key, content)
    _register_temporary_runtime_object_cleanup(
        request,
        object_key=target_object_key,
        was_generated=object_key is None,
    )
    return build_storage_image_payload(
        object_key=target_object_key,
        source_payload=normalized_source_payload,
        width=width,
        height=height,
        media_type=media_type,
    )


def infer_media_type(object_key: str) -> str:
    """根据 object key 推断媒体类型。

    参数：
    - object_key：图片 object key。

    返回：
    - str：推断后的媒体类型；未知时返回 image/png。
    """

    guessed_media_type, _ = mimetypes.guess_type(object_key)
    if isinstance(guessed_media_type, str) and guessed_media_type:
        return guessed_media_type
    return "image/png"


def infer_media_type_from_image_bytes(content: bytes) -> str:
    """根据图片字节头推断媒体类型。

    参数：
    - content：图片编码后字节。

    返回：
    - str：推断后的媒体类型；未知时返回 image/png。
    """

    if not isinstance(content, bytes) or not content:
        return "image/png"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"BM"):
        return "image/bmp"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return "image/png"


def _load_json_safe_image_bytes(
    request: WorkflowNodeExecutionRequest,
    *,
    image_payload: object,
    target_object_key: str | None = None,
) -> tuple[dict[str, object], bytes]:
    """读取图片并保证返回 bytes 是 JSON / 文件安全的编码图片。

    raw BGR24 只在这里按需编码，内部节点流转不做 PNG/JPEG 编码。
    """

    normalized_image_payload = require_image_payload(image_payload)
    if not _is_raw_image_payload(normalized_image_payload):
        _, image_bytes = load_image_bytes_from_payload(
            request,
            image_payload=normalized_image_payload,
        )
        return normalized_image_payload, image_bytes

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    _, image_matrix = load_image_matrix_from_payload(
        request,
        image_payload=normalized_image_payload,
        cv2_module=cv2,
        np_module=np,
    )
    output_extension = _resolve_encoded_output_extension(target_object_key)
    encoded_bytes = encode_matrix_to_image_bytes(
        cv2_module=cv2,
        image_matrix=image_matrix,
        extension=output_extension,
        error_message="raw 图片无法编码为对外响应图片",
    )
    safe_payload = dict(normalized_image_payload)
    safe_payload["media_type"] = infer_media_type(f"image{output_extension}")
    safe_payload["width"] = int(image_matrix.shape[1])
    safe_payload["height"] = int(image_matrix.shape[0])
    safe_payload.pop("shape", None)
    safe_payload.pop("dtype", None)
    safe_payload.pop("layout", None)
    safe_payload.pop("pixel_format", None)
    return safe_payload, encoded_bytes


def _resolve_encoded_output_extension(target_object_key: str | None) -> str:
    """为 raw 图片对外输出选择编码扩展名。"""

    if isinstance(target_object_key, str) and target_object_key.strip():
        suffix = PurePosixPath(target_object_key.strip()).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}:
            return suffix
    return ".jpg"


def _is_raw_image_payload(payload: dict[str, object]) -> bool:
    """判断 image-ref payload 是否为 raw 图片。"""

    media_type = payload.get("media_type")
    return isinstance(media_type, str) and media_type.strip().lower() == IMAGE_MEDIA_TYPE_RAW


def _read_payload_dimensions(
    payload: dict[str, object],
    *,
    fallback: tuple[int | None, int | None] = (None, None),
) -> tuple[int | None, int | None]:
    """读取图片 payload 尺寸，缺失时使用 fallback。"""

    fallback_width, fallback_height = fallback
    width = _normalize_optional_dimension(payload.get("width"))
    height = _normalize_optional_dimension(payload.get("height"))
    return (
        width if width is not None else fallback_width,
        height if height is not None else fallback_height,
    )


def _is_high_resolution_preview_image(width: int | None, height: int | None) -> bool:
    """判断 Preview 缩略展示是否需要单独 display 图。"""

    if width is None or height is None:
        return False
    pixel_count = int(width) * int(height)
    long_edge = max(int(width), int(height))
    return (
        pixel_count > PREVIEW_DISPLAY_HIGH_RESOLUTION_PIXELS
        or long_edge > PREVIEW_DISPLAY_HIGH_RESOLUTION_LONG_EDGE
    )


def infer_file_extension_from_media_type(media_type: str) -> str:
    """根据媒体类型推断文件扩展名。

    参数：
    - media_type：图片媒体类型。

    返回：
    - str：推断后的扩展名；未知时返回 .png。
    """

    guessed_extension = mimetypes.guess_extension(media_type.strip()) if isinstance(media_type, str) else None
    if isinstance(guessed_extension, str) and guessed_extension:
        return guessed_extension
    return ".png"


def _normalize_response_transport_mode(value: object) -> str:
    """规范化图片响应传输方式。"""

    normalized_value = value.strip() if isinstance(value, str) else RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64
    if normalized_value not in {
        RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64,
        RESPONSE_IMAGE_TRANSPORT_STORAGE_REF,
    }:
        raise InvalidRequestError(
            "response_transport_mode 仅支持 inline-base64 或 storage-ref",
            details={"response_transport_mode": value},
        )
    return normalized_value


def _build_default_target_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    normalized_source_payload: dict[str, object],
    variant_name: str,
    output_extension: str | None = None,
) -> str:
    """按来源模式生成默认目标 object key。"""

    source_object_key = _normalize_optional_text(normalized_source_payload.get("object_key"))
    if source_object_key is not None:
        return build_runtime_image_object_key(
            request,
            source_object_key=source_object_key,
            variant_name=variant_name,
            output_extension=output_extension,
        )

    workflow_run_id = str(request.execution_metadata.get("workflow_run_id") or "default-run")
    normalized_variant_name = variant_name.strip().replace(" ", "-") or "output"
    if output_extension is not None:
        target_extension = output_extension
    elif _is_raw_image_payload(normalized_source_payload):
        target_extension = ".jpg"
    else:
        target_extension = infer_file_extension_from_media_type(
            str(normalized_source_payload.get("media_type") or "image/png")
        )
    return f"workflows/runtime/{workflow_run_id}/{request.node_id}/{normalized_variant_name}{target_extension}"


def _register_temporary_runtime_object_cleanup(
    request: WorkflowNodeExecutionRequest,
    *,
    object_key: str,
    was_generated: bool,
) -> None:
    """为自动生成的 runtime object key 登记执行结束后的临时清理。"""

    if not was_generated:
        return
    normalized_object_key = _normalize_optional_text(object_key)
    if normalized_object_key is None:
        return
    if not _is_temporary_runtime_object_key(request, object_key=normalized_object_key):
        return
    register_dataset_storage_object_cleanup(
        request.execution_metadata,
        object_key=normalized_object_key,
    )


def _is_temporary_runtime_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    object_key: str,
) -> bool:
    """判断 object key 是否位于当前 workflow run 的临时 runtime 目录下。"""

    workflow_run_id = str(request.execution_metadata.get("workflow_run_id") or "default-run")
    return object_key.startswith(f"workflows/runtime/{workflow_run_id}/")


def _normalize_optional_dimension(value: object) -> int | None:
    """规范化可选图片尺寸字段。"""

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        normalized_value = int(value)
        return normalized_value if normalized_value >= 0 else None
    return None


def _normalize_optional_text(value: object) -> str | None:
    """规范化可选文本字段。"""

    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None
