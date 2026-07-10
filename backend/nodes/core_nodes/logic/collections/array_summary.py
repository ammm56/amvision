"""数组摘要节点。"""

from __future__ import annotations

from statistics import mean

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.collection import coerce_truthy_bool, require_list_value
from backend.nodes.core_nodes.support.logic import build_boolean_payload, build_value_payload, try_extract_value_by_path
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "array-summary"


def _array_summary_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """汇总数组的布尔和数值统计信息。"""

    items = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    path = _read_optional_path(request.parameters.get("path"))
    values: list[object] = []
    missing_count = 0
    for item_index, item in enumerate(items):
        if path is None:
            values.append(item)
            continue
        exists, extracted_value = try_extract_value_by_path(root=item, path=path)
        if exists:
            values.append(extracted_value)
            continue
        missing_count += 1
        if not _read_bool(request.parameters.get("skip_missing"), default=True):
            raise InvalidRequestError(
                f"{NODE_NAME} 节点无法从数组项提取 path",
                details={"node_id": request.node_id, "item_index": item_index, "path": path},
            )

    truthy_values = [coerce_truthy_bool(value) for value in values]
    numeric_values = [
        float(value)
        for value in values
        if not isinstance(value, bool) and isinstance(value, (int, float))
    ]
    summary = {
        "count": len(items),
        "selected_count": len(values),
        "missing_count": missing_count,
        "truthy_count": sum(1 for value in truthy_values if value),
        "falsey_count": sum(1 for value in truthy_values if not value),
        "all_truthy": all(truthy_values) if truthy_values else False,
        "any_truthy": any(truthy_values),
        "numeric_count": len(numeric_values),
        "numeric_sum": sum(numeric_values) if numeric_values else 0.0,
        "numeric_min": min(numeric_values) if numeric_values else None,
        "numeric_max": max(numeric_values) if numeric_values else None,
        "numeric_mean": mean(numeric_values) if numeric_values else None,
        "path": path,
    }
    return {
        "summary": build_value_payload(summary),
        "all": build_boolean_payload(bool(summary["all_truthy"])),
        "any": build_boolean_payload(bool(summary["any_truthy"])),
    }


def _read_optional_path(raw_value: object) -> str | None:
    """读取可选点分路径。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 path 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_bool(raw_value: object, *, default: bool) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError(f"{NODE_NAME} 节点的 skip_missing 必须是 boolean")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.array-summary",
        display_name="Array Summary",
        category="logic.collection",
        description="汇总数组的 truthy 数量和数值统计，适合 ROI 逐格判断后收敛为整体结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="all",
                display_name="All",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="any",
                display_name="Any",
                payload_type_id="boolean.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "title": "Path",
                    "description": "可选点分路径；为空时直接汇总数组项。",
                },
                "skip_missing": {"type": "boolean", "default": True, "title": "Skip Missing"},
            },
        },
        capability_tags=("logic.collection", "array.summary", "inspection.aggregate"),
    ),
    handler=_array_summary_handler,
)
