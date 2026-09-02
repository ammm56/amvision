"""模型 Batch 信封到完整关联项 List 的通用实现。"""

from __future__ import annotations

from collections.abc import Callable

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


ResultValidator = Callable[[object, str], dict[str, object]]
_LOCATOR_FIELDS = frozenset(
    {
        "image_handle",
        "object_key",
        "local_path",
        "buffer_ref",
        "frame_ref",
        "image_base64",
    }
)


def build_model_batch_to_items_node_spec(
    *,
    node_type_id: str,
    display_name: str,
    input_name: str,
    input_display_name: str,
    input_payload_type_id: str,
    format_id: str,
    task_type: str,
    result_payload_type_id: str,
    result_validator: ResultValidator,
) -> CoreNodeSpec:
    """构造校验统一 Batch 信封并输出完整关联项 List 的节点。"""

    def handle_batch_items(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        """校验信封与关联字段，保留 item_id、source 和 result。"""

        payload = request.input_values.get(input_name)
        if not isinstance(payload, dict):
            raise InvalidRequestError(
                f"{display_name} 要求输入必须是 object",
                details={"node_id": request.node_id},
            )
        _require_equal(payload, "format_id", format_id, request.node_id)
        _require_equal(payload, "task_type", task_type, request.node_id)
        _require_equal(
            payload,
            "result_payload_type_id",
            result_payload_type_id,
            request.node_id,
        )
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise InvalidRequestError(
                f"{display_name} 要求 items 必须是数组",
                details={"node_id": request.node_id},
            )
        raw_count = payload.get("count")
        if (
            isinstance(raw_count, bool)
            or not isinstance(raw_count, int)
            or raw_count != len(raw_items)
        ):
            raise InvalidRequestError(
                f"{display_name} 要求 count 与 items 数量一致",
                details={
                    "node_id": request.node_id,
                    "count": raw_count,
                    "item_count": len(raw_items),
                },
            )

        items: list[dict[str, object]] = []
        item_ids: set[str] = set()
        for item_index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                _raise_item_error(request.node_id, item_index, "item 必须是 object")
            if raw_item.get("item_index") != item_index:
                _raise_item_error(
                    request.node_id,
                    item_index,
                    "item_index 必须与数组顺序一致",
                )
            raw_item_id = raw_item.get("item_id")
            if not isinstance(raw_item_id, str) or not raw_item_id.strip():
                _raise_item_error(request.node_id, item_index, "item_id 不能为空")
            item_id = raw_item_id.strip()
            if item_id in item_ids:
                _raise_item_error(request.node_id, item_index, "item_id 不能重复")
            item_ids.add(item_id)

            source = raw_item.get("source")
            if not isinstance(source, dict):
                _raise_item_error(request.node_id, item_index, "source 必须是 object")
            locator_field = _find_locator_field(source)
            if locator_field is not None:
                _raise_item_error(
                    request.node_id,
                    item_index,
                    f"source 不能包含临时图片 locator: {locator_field}",
                )
            try:
                result = result_validator(raw_item.get("result"), request.node_id)
            except InvalidRequestError as error:
                error.details.setdefault("item_index", item_index)
                error.details.setdefault("item_id", item_id)
                raise
            items.append(
                {
                    "item_index": item_index,
                    "item_id": item_id,
                    "source": dict(source),
                    "result": result,
                }
            )
        return {"items": build_value_payload(items)}

    return CoreNodeSpec(
        node_definition=NodeDefinition(
            node_type_id=node_type_id,
            display_name=display_name,
            category="core.logic.transform",
            description=(
                "校验模型 Batch 信封并输出完整的 item_index、item_id、source、result "
                "关联记录 List；需要纯结果时显式使用 Map List(path=result)。"
            ),
            implementation_kind=NODE_IMPLEMENTATION_CORE,
            runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
            concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
            input_ports=(
                NodePortDefinition(
                    name=input_name,
                    display_name=input_display_name,
                    payload_type_id=input_payload_type_id,
                ),
            ),
            output_ports=(
                NodePortDefinition(
                    name="items",
                    display_name="Items",
                    payload_type_id="value.v1",
                ),
            ),
            parameter_schema={"type": "object", "properties": {}},
            capability_tags=(
                "logic.transform",
                "payload.batch.items",
                task_type,
            ),
        ),
        handler=handle_batch_items,
    )


def _require_equal(
    payload: dict[str, object],
    field_name: str,
    expected: str,
    node_id: str,
) -> None:
    """要求信封固定字段与当前转换节点完全匹配。"""

    if payload.get(field_name) != expected:
        raise InvalidRequestError(
            "模型 Batch 信封类型不匹配",
            details={
                "node_id": node_id,
                "field": field_name,
                "expected": expected,
                "actual": payload.get(field_name),
            },
        )


def _find_locator_field(value: object) -> str | None:
    """递归查找 Batch source 中禁止出现的临时 locator 字段。"""

    if isinstance(value, dict):
        for key, item in value.items():
            if key in _LOCATOR_FIELDS:
                return key
            nested = _find_locator_field(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_locator_field(item)
            if nested is not None:
                return nested
    return None


def _raise_item_error(node_id: str, item_index: int, message: str) -> None:
    """抛出包含稳定 Batch item 索引的请求错误。"""

    raise InvalidRequestError(
        f"模型 Batch 信封 {message}",
        details={"node_id": node_id, "item_index": item_index},
    )
