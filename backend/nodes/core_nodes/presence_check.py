"""工业存在性判断节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import (
    build_boolean_payload,
    build_value_payload,
    require_value_payload,
)
from backend.nodes.core_nodes._region_node_support import require_regions_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "presence-check"


def _presence_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """判断目标是否存在以及数量是否达标。"""

    count_value, source_kind = _resolve_count_value(request)
    min_count = _read_min_count(request.parameters.get("min_count"))
    max_count = _read_optional_max_count(request.parameters.get("max_count"))
    passed = count_value >= min_count and (max_count is None or count_value <= max_count)
    return {
        "result": build_boolean_payload(passed),
        "metrics": build_value_payload(
            {
                "count": count_value,
                "source_kind": source_kind,
                "min_count": min_count,
                "max_count": max_count,
                "result": passed,
            }
        ),
    }


def _resolve_count_value(request: WorkflowNodeExecutionRequest) -> tuple[int, str]:
    """解析 count 来源。"""

    regions_input = request.input_values.get("regions")
    value_input = request.input_values.get("value")
    if (regions_input is None and value_input is None) or (regions_input is not None and value_input is not None):
        raise InvalidRequestError(f"{NODE_NAME} 节点要求二选一提供 regions 或 value 输入")
    if regions_input is not None:
        regions_payload = require_regions_payload(regions_input, node_id=request.node_id)
        return len(regions_payload["items"]), "regions"
    value_payload = require_value_payload(value_input, field_name="value")
    raw_value = value_payload["value"]
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 value 输入必须是非负整数")
    return int(raw_value), "value"


def _read_min_count(raw_value: object) -> int:
    """读取最小数量阈值。"""

    if raw_value is None:
        return 1
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 min_count 必须是非负整数")
    return int(raw_value)


def _read_optional_max_count(raw_value: object) -> int | None:
    """读取可选最大数量阈值。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_count 必须是非负整数")
    return int(raw_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.rule.presence-check",
        display_name="Presence Check",
        category="rule.condition",
        description="对区域数量或显式 count 执行存在性与数量达标判断，适合有没有、几个、是否超上限这类工业规则。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                required=False,
            ),
            NodePortDefinition(
                name="value",
                display_name="Count Value",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "min_count": {"type": "integer", "title": "最小数量", "default": 1, "minimum": 0},
                "max_count": {"type": "integer", "title": "最大数量", "minimum": 0},
            },
        },
        capability_tags=("rule.condition", "inspection.presence", "inspection.count"),
    ),
    handler=_presence_check_handler,
)
