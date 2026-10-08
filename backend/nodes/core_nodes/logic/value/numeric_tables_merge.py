"""合并同次观察的数值表，供通用多分支规则检查。"""

from pydantic import ValidationError

from backend.contracts.workflows.metrology import NumericTable
from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.service.application.errors import InvalidRequestError


def handle_node(request) -> dict:
    """拒绝混合观察 ID、重复项和超限结果，不覆盖同名数值。"""
    raw = request.input_values.get("tables")
    if not isinstance(raw, tuple) or not 1 <= len(raw) <= 64:
        raise InvalidRequestError("Merge Numeric Tables 需要 1–64 个数值表")
    try:
        tables = [NumericTable.model_validate(item) for item in raw]
        if len({table.observation_id for table in tables}) != 1:
            raise ValueError("数值表不属于同次观察")
        if sum(len(table.items) for table in tables) > 8192:
            raise ValueError("合并数值项超过 8192")
        merged = NumericTable(
            observation_id=tables[0].observation_id,
            items=tuple(item for table in tables for item in table.items),
        )
    except (ValueError, ValidationError) as exc:
        raise InvalidRequestError(str(exc)) from exc
    return {"table": merged.model_dump(mode="json")}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.value.numeric-tables-merge",
        display_name="Merge Numeric Tables",
        category="core.logic.transform",
        description="合并同次观察的数值表；错帧和同名项报错，保留无效值及单位。",
        implementation_kind="core-node",
        runtime_kind="python-callable",
        input_ports=(
            NodePortDefinition(
                name="tables",
                display_name="Tables",
                payload_type_id="numeric-table.v1",
                multiple=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="table", display_name="Table", payload_type_id="numeric-table.v1"
            ),
        ),
    ),
    handler=handle_node,
)
