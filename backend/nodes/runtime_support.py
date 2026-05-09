"""节点运行时的图片与文件 helper。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import mimetypes
from pathlib import PurePosixPath
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.execution_cleanup import register_dataset_storage_object_cleanup
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


IMAGE_TRANSPORT_MEMORY = "memory"
IMAGE_TRANSPORT_STORAGE = "storage"
RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64 = "inline-base64"
RESPONSE_IMAGE_TRANSPORT_STORAGE_REF = "storage-ref"


@dataclass(frozen=True)
class ExecutionImageEntry:
    """描述 execution image registry 中的一张图片。

    字段：
    - image_handle：当前执行范围内的图片句柄。
    - content：图片的编码后字节。
    - media_type：图片媒体类型。
    - width：图片宽度。
    - height：图片高度。
    - byte_length：图片字节长度。
    - created_by_node_id：创建该图片的节点 id。
    """

    image_handle: str
    content: bytes
    media_type: str
    width: int | None = None
    height: int | None = None
    byte_length: int = 0
    created_by_node_id: str | None = None


@dataclass(frozen=True)
class ResolvedImageInput:
    """描述一次图片输入解析后的统一视图。

    字段：
    - payload：规范化后的 image-ref payload。
    - transport_kind：图片传输方式，支持 memory 或 storage。
    - media_type：图片媒体类型。
    - width：图片宽度。
    - height：图片高度。
    - object_key：storage 模式下的本地 object key。
    - image_handle：memory 模式下的执行期图片句柄。
    """

    payload: dict[str, object]
    transport_kind: str
    media_type: str
    width: int | None = None
    height: int | None = None
    object_key: str | None = None
    image_handle: str | None = None


class ExecutionImageRegistry:
    """在单次 workflow 执行范围内管理内存图片引用。"""

    def __init__(self) -> None:
        """初始化空的 execution image registry。"""

        self._entries: dict[str, ExecutionImageEntry] = {}

    def register_image_bytes(
        self,
        *,
        content: bytes,
        media_type: str,
        width: int | None = None,
        height: int | None = None,
        created_by_node_id: str | None = None,
    ) -> ExecutionImageEntry:
        """注册一张内存图片并返回稳定条目。

        参数：
        - content：图片编码后字节。
        - media_type：图片媒体类型。
        - width：图片宽度。
        - height：图片高度。
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
            created_by_node_id=_normalize_optional_text(created_by_node_id),
        )
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

        return self.get_entry(image_handle).content

    def release(self, image_handle: str) -> None:
        """释放一张已注册的内存图片。

        参数：
        - image_handle：图片句柄。
        """

        normalized_image_handle = image_handle.strip() if isinstance(image_handle, str) else ""
        if normalized_image_handle:
            self._entries.pop(normalized_image_handle, None)

    def clear(self) -> None:
        """清空当前执行范围内的全部图片。"""

        self._entries.clear()


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

    if not normalized_transport_kind:
        if isinstance(object_key, str) and object_key.strip():
            normalized_transport_kind = IMAGE_TRANSPORT_STORAGE
        elif isinstance(image_handle, str) and image_handle.strip():
            normalized_transport_kind = IMAGE_TRANSPORT_MEMORY

    if normalized_transport_kind not in {IMAGE_TRANSPORT_MEMORY, IMAGE_TRANSPORT_STORAGE}:
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
    else:
        if not isinstance(image_handle, str) or not image_handle.strip():
            raise InvalidRequestError("memory image-ref payload 缺少有效 image_handle")
        normalized_payload["image_handle"] = image_handle.strip()
        normalized_payload.pop("object_key", None)
        media_type = normalized_payload.get("media_type")
        if not isinstance(media_type, str) or not media_type.strip():
            raise InvalidRequestError("memory image-ref payload 缺少有效 media_type")
        normalized_payload["media_type"] = media_type.strip()

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
    return normalized_payload


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
    return ResolvedImageInput(
        payload=payload,
        transport_kind=str(payload["transport_kind"]),
        media_type=str(payload["media_type"]),
        width=_normalize_optional_dimension(payload.get("width")),
        height=_normalize_optional_dimension(payload.get("height")),
        object_key=_normalize_optional_text(payload.get("object_key")),
        image_handle=_normalize_optional_text(payload.get("image_handle")),
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

    resolved_image = ResolvedImageInput(
        payload=require_image_payload(image_payload),
        transport_kind=str(require_image_payload(image_payload)["transport_kind"]),
        media_type=str(require_image_payload(image_payload)["media_type"]),
        width=_normalize_optional_dimension(require_image_payload(image_payload).get("width")),
        height=_normalize_optional_dimension(require_image_payload(image_payload).get("height")),
        object_key=_normalize_optional_text(require_image_payload(image_payload).get("object_key")),
        image_handle=_normalize_optional_text(require_image_payload(image_payload).get("image_handle")),
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

    image_registry = require_execution_image_registry(request)
    assert resolved_image.image_handle is not None
    return dict(resolved_image.payload), image_registry.read_bytes(resolved_image.image_handle)


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
) -> dict[str, object]:
    """构建 memory 模式 image-ref payload。

    参数：
    - image_handle：执行期图片句柄。
    - media_type：图片媒体类型。
    - width：图片宽度。
    - height：图片高度。

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
    created_by_node_id: str | None = None,
) -> dict[str, object]:
    """把图片字节注册到 execution image registry，并返回 memory payload。

    参数：
    - request：当前节点执行请求。
    - content：图片编码后字节。
    - media_type：图片媒体类型。
    - width：图片宽度。
    - height：图片高度。
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
        created_by_node_id=created_by_node_id or request.node_id,
    )
    return build_memory_image_payload(
        image_handle=image_entry.image_handle,
        media_type=image_entry.media_type,
        width=image_entry.width,
        height=image_entry.height,
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
    normalized_image_payload, image_bytes = load_image_bytes_from_payload(
        request,
        image_payload=image_payload,
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

    if normalized_image_payload["transport_kind"] == IMAGE_TRANSPORT_STORAGE and object_key is None:
        stored_payload = build_storage_image_payload(
            object_key=str(normalized_image_payload["object_key"]),
            source_payload=normalized_image_payload,
        )
    else:
        stored_payload = copy_image_payload(
            request,
            source_payload=normalized_image_payload,
            object_key=object_key,
            overwrite=overwrite,
            variant_name=variant_name,
        )
    response_image["object_key"] = str(stored_payload["object_key"])
    return response_image


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
    if normalized_source_payload["transport_kind"] == IMAGE_TRANSPORT_STORAGE and source_object_key is not None:
        if target_object_key != source_object_key:
            dataset_storage.copy_relative_file(source_object_key, target_object_key)
    else:
        image_registry = require_execution_image_registry(request)
        image_handle = str(normalized_source_payload["image_handle"])
        dataset_storage.write_bytes(target_object_key, image_registry.read_bytes(image_handle))
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
    target_extension = output_extension or infer_file_extension_from_media_type(
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