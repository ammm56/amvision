"""image-refs 单项读取节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _image_refs_item_get_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按索引从 image-refs.v1 里读取单个 image-ref.v1。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含单张图片引用的节点输出。
    """

    image_refs_payload = _require_image_refs_payload(request.input_values.get("images"), node_id=request.node_id)
    resolved_index = _resolve_index(request)
    items = image_refs_payload["items"]
    normalized_index = resolved_index
    allow_negative = _read_optional_bool(request.parameters.get("allow_negative"), default=True)
    if normalized_index < 0 and allow_negative:
        normalized_index += len(items)
    if 0 <= normalized_index < len(items):
        return {"image": dict(items[normalized_index])}
    raise InvalidRequestError(
        "image-refs-item-get 节点索引越界",
        details={
            "node_id": request.node_id,
            "index": resolved_index,
            "normalized_index": normalized_index,
            "size": len(items),
        },
    )


def _require_image_refs_payload(payload: object, *, node_id: str) -> dict[str, tuple[dict[str, object], ...]]:
    """校验 image-refs.v1 payload 并返回规范化结果。

    参数：
    - payload：待校验的 image-refs 输入 payload。
    - node_id：当前节点 id，用于错误上下文。

    返回：
    - dict[str, tuple[dict[str, object], ...]]：只包含规范化 items 的结果。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "image-refs-item-get 节点要求 images payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError(
            "image-refs-item-get 节点要求 images.items 必须是非空数组",
            details={"node_id": node_id},
        )
    normalized_items: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        try:
            normalized_items.append(require_image_payload(raw_item))
        except InvalidRequestError as exc:
            raise InvalidRequestError(
                "image-refs-item-get 节点要求每个 images.items 都必须是有效 image-ref",
                details={"node_id": node_id, "item_index": item_index, **(exc.details or {})},
            ) from exc
    return {"items": tuple(normalized_items)}


def _resolve_index(request: WorkflowNodeExecutionRequest) -> int:
    """从输入端口或参数读取索引。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - int：已经过类型校验的索引值。
    """

    index_payload = request.input_values.get("index")
    if index_payload is not None:
        raw_index = require_value_payload(index_payload, field_name="index")["value"]
    else:
        raw_index = request.parameters.get("index", 0)
    if isinstance(raw_index, bool) or not isinstance(raw_index, int):
        raise InvalidRequestError(
            "image-refs-item-get 节点要求 index 必须是整数",
            details={"node_id": request.node_id, "index": raw_index},
        )
    return raw_index


def _read_optional_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。

    参数：
    - raw_value：待读取的原始参数值。
    - default：参数缺失时返回的默认值。

    返回：
    - bool：规范化后的布尔值。
    """

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError("image-refs-item-get 节点的 allow_negative 必须是布尔值")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-refs-item-get",
        display_name="Get Image Ref",
        category="io.image",
        description="按索引从 image-refs.v1 里选出一张 image-ref.v1，适合 crop-export 后接 image-preview 或后续单图 OpenCV 节点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="images",
                display_name="Images",
                payload_type_id="image-refs.v1",
            ),
            NodePortDefinition(
                name="index",
                display_name="Index",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "default": 0,
                    "title": "索引",
                    "description": "默认选第 1 张裁剪图；也可以从 index 输入端口动态指定。",
                },
                "allow_negative": {
                    "type": "boolean",
                    "default": True,
                    "title": "允许负索引",
                    "description": "为 true 时，-1 表示最后一张图。",
                },
            },
        },
        capability_tags=("io.image", "image.refs.read"),
    ),
    handler=_image_refs_item_get_handler,
)