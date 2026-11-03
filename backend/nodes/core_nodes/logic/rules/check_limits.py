"""按稳定 ID 检查通用数值表的多个上下限。"""

from pydantic import TypeAdapter, ValidationError

from backend.contracts.workflows.metrology import LimitRule, NumericTable
from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import (
    build_boolean_payload,
    build_value_payload,
)
from backend.nodes.core_nodes.support.measurement import check_limits
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict:
    """严格校验规则，区分执行错误、无法判定和可靠超差。"""
    try:
        table = NumericTable.model_validate(request.input_values.get("table"))
        rules = TypeAdapter(tuple[LimitRule, ...]).validate_python(
            request.parameters.get("rules", [])
        )
        result = check_limits(table, rules)
    except (ValidationError, ValueError) as exc:
        raise InvalidRequestError(f"Check Limits 配置或数值表无效: {exc}") from exc
    return {
        "result": build_boolean_payload(result["passed"]),
        "summary": build_value_payload(result),
    }


_rules_schema = TypeAdapter(list[LimitRule]).json_schema()
_rules_schema.update({"title": "Rules", "maxItems": 8192, "x-ui-widget": "object-rows"})
# 表格需要内联行字段，避免编辑器自行解析 Python 类型名。
_rules_schema["items"] = _rules_schema.pop("$defs")["LimitRule"]

CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.rule.check-limits",
        version="1.0.0",
        metadata={"requires_execution_review": True},
        display_name="Check Limits",
        category="core.logic.rule",
        description="按检查项 ID 输出 OK/NG/INVALID 完整摘要；Result 仅表示可放行，Summary 保留原因与逐项证据。",
        implementation_kind="core-node",
        runtime_kind="python-callable",
        input_ports=(
            NodePortDefinition(
                name="table", display_name="Values", payload_type_id="numeric-table.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result", display_name="Result", payload_type_id="boolean.v1"
            ),
            NodePortDefinition(
                name="summary", display_name="Summary", payload_type_id="value.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {"rules": _rules_schema},
            "required": ["rules"],
            "additionalProperties": False,
        },
        capability_tags=("rule.condition", "inspection.range"),
    ),
    handler=handle_node,
)
