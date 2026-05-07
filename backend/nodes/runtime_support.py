"""节点运行时的图片与文件 helper。"""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


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


def require_image_payload(payload: object) -> dict[str, object]:
    """校验并规范化 image-ref payload。

    参数：
    - payload：待校验的输入 payload。

    返回：
    - dict[str, object]：标准化后的图片引用 payload。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("图片节点要求 image-ref payload 必须是对象")
    object_key = payload.get("object_key")
    if not isinstance(object_key, str) or not object_key.strip():
        raise InvalidRequestError("image-ref payload 缺少有效 object_key")
    normalized_payload = dict(payload)
    normalized_payload["object_key"] = object_key.strip()
    media_type = normalized_payload.get("media_type")
    if not isinstance(media_type, str) or not media_type.strip():
        normalized_payload["media_type"] = infer_media_type(normalized_payload["object_key"])
    return normalized_payload


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
    payload = require_image_payload(request.input_values.get(input_name))
    object_key = str(payload["object_key"])
    source_path = dataset_storage.resolve(object_key)
    if not source_path.is_file():
        raise InvalidRequestError(
            "图片节点引用的 object_key 不存在",
            details={"node_id": request.node_id, "object_key": object_key},
        )
    return dataset_storage, payload, object_key


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

    image_payload = {"object_key": object_key}
    resolved_width = width if width is not None else source_payload.get("width")
    resolved_height = height if height is not None else source_payload.get("height")
    if isinstance(resolved_width, int):
        image_payload["width"] = resolved_width
    if isinstance(resolved_height, int):
        image_payload["height"] = resolved_height
    image_payload["media_type"] = media_type or infer_media_type(object_key)
    return image_payload


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
    source_object_key = str(normalized_source_payload["object_key"])
    target_object_key = object_key or build_runtime_image_object_key(
        request,
        source_object_key=source_object_key,
        variant_name=variant_name,
    )
    target_path = dataset_storage.resolve(target_object_key)
    if target_path.exists() and not overwrite and target_object_key != source_object_key:
        raise InvalidRequestError(
            "图片保存目标已存在，且当前节点未允许覆盖",
            details={"node_id": request.node_id, "object_key": target_object_key},
        )
    if target_object_key != source_object_key:
        dataset_storage.copy_relative_file(source_object_key, target_object_key)
    return build_image_payload(
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
    target_object_key = object_key or build_runtime_image_object_key(
        request,
        source_object_key=str(normalized_source_payload["object_key"]),
        variant_name=variant_name,
        output_extension=output_extension,
    )
    dataset_storage.write_bytes(target_object_key, content)
    return build_image_payload(
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