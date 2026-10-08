"""通用数值表到普通值对象的显式转换节点。"""

from pydantic import ValidationError

from backend.contracts.workflows.metrology import NumericTable
from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.measurement import numeric_table_to_value
from backend.service.application.errors import InvalidRequestError


def handle_node(request) -> dict:
    """保留原始精度与无效 null，供通用提取、显示或显式保存节点使用。"""
    try:
        table = NumericTable.model_validate(request.input_values.get("table"))
    except ValidationError as exc:
        raise InvalidRequestError(f"数值表无效: {exc}") from exc
    return {"value": build_value_payload(numeric_table_to_value(table))}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.value.numeric-table-to-value",
        display_name="Numeric Table To Value",
        category="core.logic.transform",
        description="将数值表转换为包含 values 与逐项有效性的普通对象，供提取、显示与记录。",
        implementation_kind="core-node",
        runtime_kind="python-callable",
        input_ports=(
            NodePortDefinition(
                name="table", display_name="Values", payload_type_id="numeric-table.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value", display_name="Value", payload_type_id="value.v1"
            ),
        ),
    ),
    handler=handle_node,
)
