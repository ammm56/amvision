"""工业 OK / NG 汇总节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import (
    build_boolean_payload,
    build_value_payload,
    require_boolean_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "ok-ng-decision"


def _ok_ng_decision_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把多路布尔条件收成 OK / NG 判定。"""

    raw_conditions = request.input_values.get("conditions")
    if raw_conditions is None or not isinstance(raw_conditions, tuple) or len(raw_conditions) == 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点要求至少连接一个 conditions 输入")
    condition_values: list[bool] = []
    for condition_index, condition_payload in enumerate(raw_conditions, start=1):
        normalized_payload = require_boolean_payload(condition_payload, field_name=f"conditions[{condition_index}]")
        condition_values.append(bool(normalized_payload["value"]))
    mode = _read_mode(request.parameters.get("mode"))
    passed = all(condition_values) if mode == "all" else any(condition_values)
    ok_label = _read_label(request.parameters.get("ok_label"), default_value="OK")
    ng_label = _read_label(request.parameters.get("ng_label"), default_value="NG")
    decision_value = ok_label if passed else ng_label
    passed_indexes = [index for index, item in enumerate(condition_values, start=1) if item]
    failed_indexes = [index for index, item in enumerate(condition_values, start=1) if not item]
    return {
        "decision": build_value_payload(decision_value),
        "ok": build_boolean_payload(passed),
        "summary": build_value_payload(
            {
                "ok_ng": decision_value,
                "mode": mode,
                "condition_count": len(condition_values),
                "passed_count": len(passed_indexes),
                "failed_count": len(failed_indexes),
                "passed_indexes": passed_indexes,
                "failed_indexes": failed_indexes,
                "result": passed,
            }
        ),
    }


def _read_mode(raw_value: object) -> str:
    """读取判定模式。"""

    if raw_value is None:
        return "all"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"all", "any"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点仅支持 all 或 any")
    return normalized_value


def _read_label(raw_value: object, *, default_value: str) -> str:
    """读取 OK / NG 标签。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 节点的标签参数必须是非空字符串")
    return raw_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.rule.ok-ng-decision",
        display_name="OK / NG Decision",
        category="rule.decision",
        description="把多路布尔条件汇总为最终 OK / NG 判定，适合把面积、覆盖率、落位等规则收成单一结论。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="conditions",
                display_name="Conditions",
                payload_type_id="boolean.v1",
                multiple=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="decision",
                display_name="Decision",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="ok",
                display_name="OK",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["all", "any"],
                    "default": "all",
                    "title": "判定模式",
                },
                "ok_label": {"type": "string", "title": "OK 标签", "default": "OK"},
                "ng_label": {"type": "string", "title": "NG 标签", "default": "NG"},
            },
        },
        capability_tags=("rule.decision", "inspection.ok-ng", "inspection.rule"),
    ),
    handler=_ok_ng_decision_handler,
)
