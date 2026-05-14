"""base64 图片解码节点。"""

from __future__ import annotations

import base64
import binascii

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.runtime_support import infer_media_type_from_image_bytes, register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _image_base64_decode_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 image-base64 输入解码为 execution-scoped memory image-ref。

    参数：
    - request：当前节点执行请求。

    返回：
    - dict[str, object]：包含解码后 memory image-ref 的节点输出。
    """

    payload = _require_image_base64_payload(request.input_values.get("payload"))
    try:
        content = base64.b64decode(payload["image_base64"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidRequestError(
            "image-base64 payload 不是有效的 base64 图片",
            details={"node_id": request.node_id},
        ) from exc
    if not content:
        raise InvalidRequestError(
            "image-base64 payload 解码后不能为空",
            details={"node_id": request.node_id},
        )

    media_type = payload.get("media_type")
    normalized_media_type = (
        media_type.strip()
        if isinstance(media_type, str) and media_type.strip()
        else infer_media_type_from_image_bytes(content)
    )
    return {
        "image": register_image_bytes(
            request,
            content=content,
            media_type=normalized_media_type,
            width=_normalize_optional_dimension(payload.get("width")),
            height=_normalize_optional_dimension(payload.get("height")),
        )
    }


def _require_image_base64_payload(payload: object) -> dict[str, object]:
    """校验并规范化 image-base64 输入 payload。

    参数：
    - payload：待校验的原始 payload。

    返回：
    - dict[str, object]：规范化后的 payload。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("image-base64 节点要求 payload 必须是对象")
    raw_image_base64 = payload.get("image_base64")
    if not isinstance(raw_image_base64, str) or not raw_image_base64.strip():
        raise InvalidRequestError("image-base64 payload 缺少有效 image_base64")

    normalized_payload = dict(payload)
    normalized_image_base64 = raw_image_base64.strip()
    if normalized_image_base64.startswith("data:"):
        normalized_image_base64, data_url_media_type = _split_data_url_payload(normalized_image_base64)
        if (
            not isinstance(normalized_payload.get("media_type"), str)
            or not str(normalized_payload.get("media_type") or "").strip()
        ) and data_url_media_type is not None:
            normalized_payload["media_type"] = data_url_media_type

    normalized_payload["image_base64"] = "".join(normalized_image_base64.split())
    if not normalized_payload["image_base64"]:
        raise InvalidRequestError("image-base64 payload 缺少有效 image_base64")

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


def _split_data_url_payload(value: str) -> tuple[str, str | None]:
    """拆分 data URL 形式的 base64 图片字符串。

    参数：
    - value：原始 data URL 文本。

    返回：
    - tuple[str, str | None]：纯 base64 文本与可选 media_type。
    """

    header, separator, encoded_payload = value.partition(",")
    if separator != "," or ";base64" not in header:
        raise InvalidRequestError("image-base64 data URL 格式无效")
    media_type = header[len("data:") : header.index(";base64")].strip() or None
    return encoded_payload.strip(), media_type


def _normalize_optional_dimension(value: object) -> int | None:
    """规范化可选图片尺寸字段。"""

    if isinstance(value, int) and value > 0:
        return value
    return None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-base64-decode",
        display_name="Image Base64 Decode",
        category="io.transform",
        description="把 image-base64 输入解码为 execution-scoped memory image-ref。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="payload",
                display_name="Payload",
                payload_type_id="image-base64.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("io.transform", "image.decode", "image.memory"),
    ),
    handler=_image_base64_decode_handler,
)