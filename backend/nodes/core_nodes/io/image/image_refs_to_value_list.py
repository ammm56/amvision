"""image-refs 转 for-each 可迭代 value 列表节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "image-refs-to-value-list"


def _image_refs_to_value_list_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 image-refs.v1 的 items 转成 value.v1 数组。

    这个节点只做类型桥接，不复制图片内容。输出数组里的每一项仍然是
    image-ref payload，可直接作为 for-each 的 items 输入，再在循环体中用
    Value To Image Ref 恢复为 image-ref.v1。
    """

    image_refs_payload = _require_image_refs_payload(request.input_values.get("images"), node_id=request.node_id)
    image_items = [dict(item) for item in image_refs_payload["items"]]
    return {
        "items": build_value_payload(image_items),
        "summary": build_value_payload(
            {
                "count": len(image_items),
                "empty": not image_items,
                "source_format_id": image_refs_payload.get("format_id"),
            }
        ),
    }


def _require_image_refs_payload(payload: object, *, node_id: str) -> dict[str, object]:
    """校验 image-refs.v1，并规范化内部 image-ref 项。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            f"{NODE_NAME} 节点要求 images payload 必须是对象",
            details={"node_id": node_id},
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            f"{NODE_NAME} 节点要求 images.items 必须是数组",
            details={"node_id": node_id},
        )
    normalized_items: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        try:
            normalized_items.append(require_image_payload(raw_item))
        except InvalidRequestError as exc:
            raise InvalidRequestError(
                f"{NODE_NAME} 节点要求每个 images.items 都必须是有效 image-ref",
                details={"node_id": node_id, "item_index": item_index, **(exc.details or {})},
            ) from exc
    return {
        "format_id": payload.get("format_id"),
        "items": normalized_items,
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-refs-to-value-list",
        display_name="Image Refs To Value List",
        category="io.image",
        description="把 image-refs.v1 中的图片引用数组转换为 for-each 可迭代的 value.v1 数组，不复制图片内容。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="images",
                display_name="Images",
                payload_type_id="image-refs.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("io.image", "image.refs", "logic.iteration"),
    ),
    handler=_image_refs_to_value_list_handler,
)
