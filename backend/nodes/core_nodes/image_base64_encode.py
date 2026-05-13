"""图片引用转 image-base64 节点。"""

from __future__ import annotations

import base64

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.runtime_support import load_image_bytes_from_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _normalize_optional_dimension(value: object) -> int | None:
    """把可选图片尺寸规范化为正整数。

    参数：
    - value：待规范化的尺寸值。

    返回：
    - int | None：合法正整数时返回对应值，否则返回 None。
    """

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        normalized_value = int(value)
        return normalized_value if normalized_value > 0 and normalized_value == value else None
    return None


def _image_base64_encode_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 image-ref 输入编码为 image-base64 payload。

    参数：
    - request：当前节点执行请求。

    返回：
    - dict[str, object]：编码后的 image-base64 输出；输入缺失时返回空输出占位。
    """

    image_payload = request.input_values.get("image")
    if image_payload is None:
        return {"payload": None}

    normalized_payload, image_bytes = load_image_bytes_from_payload(
        request,
        image_payload=image_payload,
    )
    output_payload: dict[str, object] = {
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        "media_type": str(normalized_payload["media_type"]),
    }
    normalized_width = _normalize_optional_dimension(normalized_payload.get("width"))
    normalized_height = _normalize_optional_dimension(normalized_payload.get("height"))
    if normalized_width is not None:
        output_payload["width"] = normalized_width
    if normalized_height is not None:
        output_payload["height"] = normalized_height
    return {"payload": output_payload}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-base64-encode",
        display_name="Image Base64 Encode",
        category="io.transform",
        description="把 image-ref 输入编码为 image-base64.v1，便于后续复用既有 base64 图链路。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="payload",
                display_name="Payload",
                payload_type_id="image-base64.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("io.transform", "image.encode", "image.base64"),
    ),
    handler=_image_base64_encode_handler,
)