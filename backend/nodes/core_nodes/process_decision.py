"""工业工艺判定对象节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._inspection_record_node_support import (
    build_result_record_payload,
    read_optional_reason_input,
    read_optional_value_input,
)
from backend.nodes.core_nodes._logic_node_support import (
    build_boolean_payload,
    build_value_payload,
    require_boolean_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "process-decision"


def _process_decision_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把多路条件、指标和上下文直接收成工艺判定结果对象。"""

    raw_conditions = request.input_values.get("conditions")
    if raw_conditions is None or not isinstance(raw_conditions, tuple) or len(raw_conditions) == 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点要求至少连接一个 conditions 输入")
    mode = _read_mode(request.parameters.get("mode"))
    condition_names = _read_condition_names(request.parameters.get("condition_names"))
    condition_items: list[dict[str, object]] = []
    condition_values: list[bool] = []
    for condition_index, condition_payload in enumerate(raw_conditions, start=1):
        normalized_payload = require_boolean_payload(condition_payload, field_name=f"conditions[{condition_index}]")
        condition_value = bool(normalized_payload["value"])
        condition_values.append(condition_value)
        condition_items.append(
            {
                "index": condition_index,
                "name": condition_names[condition_index - 1] if condition_index - 1 < len(condition_names) else f"condition-{condition_index}",
                "passed": condition_value,
            }
        )
    passed = all(condition_values) if mode == "all" else any(condition_values)
    ok_ng = "OK" if passed else "NG"
    metrics_value = read_optional_value_input(request.input_values.get("metrics"), field_name="metrics")
    metadata_value = read_optional_value_input(request.input_values.get("metadata"), field_name="metadata")
    reason_value = read_optional_reason_input(request.input_values.get("reason"))
    if reason_value is None:
        reason_value = _read_default_reason(request.parameters.get("ok_reason" if passed else "ng_reason"))
    result_payload = build_result_record_payload(
        ok_ng=ok_ng,
        metrics_value=metrics_value,
        conditions_value=condition_items,
        reason_value=reason_value,
        metadata_value=metadata_value,
        alarm_payload=request.input_values.get("alarm"),
        image_payload=request.input_values.get("image"),
        video_payload=request.input_values.get("video"),
    )
    passed_names = [item["name"] for item in condition_items if bool(item["passed"])]
    failed_names = [item["name"] for item in condition_items if not bool(item["passed"])]
    return {
        "result": result_payload,
        "decision": build_value_payload(ok_ng),
        "ok": build_boolean_payload(passed),
        "summary": build_value_payload(
            {
                "ok_ng": ok_ng,
                "mode": mode,
                "condition_count": len(condition_items),
                "passed_count": len(passed_names),
                "failed_count": len(failed_names),
                "passed_condition_names": passed_names,
                "failed_condition_names": failed_names,
                "has_alarm": "alarm" in result_payload,
                "result": passed,
            }
        ),
    }


def _read_mode(raw_value: object) -> str:
    """读取条件聚合模式。"""

    if raw_value is None:
        return "all"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"all", "any"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 mode 仅支持 all 或 any")
    return normalized_value


def _read_condition_names(raw_value: object) -> list[str]:
    """读取条件名称列表。"""

    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 condition_names 必须是字符串数组")
    normalized_names: list[str] = []
    for item_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, str) or not item_value.strip():
            raise InvalidRequestError(
                f"{NODE_NAME} 节点的 condition_names 必须全部是非空字符串",
                details={"item_index": item_index},
            )
        normalized_names.append(item_value.strip())
    return normalized_names


def _read_default_reason(raw_value: object) -> str | None:
    """读取可选默认原因文案。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 节点的默认 reason 参数必须是非空字符串")
    return raw_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.rule.process-decision",
        display_name="Process Decision",
        category="rule.decision",
        description="把多路布尔条件、指标和上下文直接组装成工艺判定结果对象，适合现场把多项规则一次收成 OK/NG。", 
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="conditions",
                display_name="Conditions",
                payload_type_id="boolean.v1",
                multiple=True,
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="reason",
                display_name="Reason",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="metadata",
                display_name="Metadata",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="alarm",
                display_name="Alarm",
                payload_type_id="alarm-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                required=False,
            ),
            NodePortDefinition(
                name="video",
                display_name="Video",
                payload_type_id="video-ref.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="result-record.v1",
            ),
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
                    "title": "聚合模式",
                },
                "condition_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "条件名称列表",
                },
                "ok_reason": {"type": "string", "title": "OK 默认原因"},
                "ng_reason": {"type": "string", "title": "NG 默认原因"},
            },
        },
        capability_tags=("rule.decision", "inspection.ok-ng", "inspection.process.decision"),
    ),
    handler=_process_decision_handler,
)
