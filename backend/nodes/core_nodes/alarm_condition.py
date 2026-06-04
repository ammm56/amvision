"""工业报警条件节点。"""

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
    require_boolean_payload,
    require_value_payload,
)
from backend.nodes.core_nodes._inspection_record_node_support import require_alarm_record_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "alarm-condition"


def _alarm_condition_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据布尔条件生成报警对象。"""

    condition_payload = require_boolean_payload(request.input_values.get("condition"), field_name="condition")
    trigger_when = _read_trigger_when(request.parameters.get("trigger_when"))
    alarm_active = bool(condition_payload["value"]) if trigger_when == "condition-true" else not bool(condition_payload["value"])
    alarm_level = _read_alarm_level(request.parameters.get("alarm_level"))
    alarm_code = _read_optional_code(request.parameters.get("alarm_code"))
    alarm_message = _resolve_message(
        request,
        alarm_active=alarm_active,
        default_active_message="alarm active",
        default_inactive_message="alarm clear",
    )
    alarm_payload: dict[str, object] = {
        "active": alarm_active,
        "level": alarm_level,
        "message": alarm_message,
    }
    if alarm_code is not None:
        alarm_payload["code"] = alarm_code
    if request.input_values.get("metrics") is not None:
        alarm_payload["metrics"] = require_value_payload(request.input_values.get("metrics"), field_name="metrics")["value"]
    if request.input_values.get("metadata") is not None:
        metadata_value = require_value_payload(request.input_values.get("metadata"), field_name="metadata")["value"]
        if not isinstance(metadata_value, dict):
            raise InvalidRequestError(f"{NODE_NAME} 节点的 metadata 输入必须是对象")
        alarm_payload["metadata"] = metadata_value
    if request.input_values.get("image") is not None:
        alarm_payload["image"] = request.input_values.get("image")
    if request.input_values.get("video") is not None:
        alarm_payload["video"] = request.input_values.get("video")
    normalized_alarm_payload = require_alarm_record_payload(alarm_payload)
    return {
        "alarm": normalized_alarm_payload,
        "active": build_boolean_payload(alarm_active),
        "summary": build_value_payload(
            {
                "trigger_when": trigger_when,
                "condition_value": bool(condition_payload["value"]),
                "alarm_active": alarm_active,
                "level": alarm_level,
                "code": alarm_code,
            }
        ),
    }


def _read_trigger_when(raw_value: object) -> str:
    """读取报警触发方向。"""

    if raw_value is None:
        return "condition-false"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 trigger_when 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"condition-true", "condition-false"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 trigger_when 仅支持 condition-true 或 condition-false")
    return normalized_value


def _read_alarm_level(raw_value: object) -> str:
    """读取报警级别。"""

    if raw_value is None:
        return "warning"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 alarm_level 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"info", "warning", "error", "critical"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 alarm_level 仅支持 info/warning/error/critical")
    return normalized_value


def _read_optional_code(raw_value: object) -> str | None:
    """读取可选报警码。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 节点的 alarm_code 必须是非空字符串")
    return raw_value.strip()


def _resolve_message(
    request: WorkflowNodeExecutionRequest,
    *,
    alarm_active: bool,
    default_active_message: str,
    default_inactive_message: str,
) -> str:
    """解析报警文案。"""

    if alarm_active and request.input_values.get("message") is not None:
        message_value = require_value_payload(request.input_values.get("message"), field_name="message")["value"]
        if not isinstance(message_value, str) or not message_value.strip():
            raise InvalidRequestError(f"{NODE_NAME} 节点的 message 输入必须是非空字符串")
        return message_value.strip()
    parameter_name = "alarm_message" if alarm_active else "clear_message"
    default_value = default_active_message if alarm_active else default_inactive_message
    raw_value = request.parameters.get(parameter_name)
    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {parameter_name} 必须是非空字符串")
    return raw_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.rule.alarm-condition",
        display_name="Alarm Condition",
        category="rule.decision",
        description="根据布尔条件生成报警对象，适合把规则失败直接收成 warning/error/critical 报警记录。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="condition",
                display_name="Condition",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="message",
                display_name="Message",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
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
                name="alarm",
                display_name="Alarm",
                payload_type_id="alarm-record.v1",
            ),
            NodePortDefinition(
                name="active",
                display_name="Active",
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
                "trigger_when": {
                    "type": "string",
                    "enum": ["condition-false", "condition-true"],
                    "default": "condition-false",
                    "title": "触发方向",
                },
                "alarm_level": {
                    "type": "string",
                    "enum": ["info", "warning", "error", "critical"],
                    "default": "warning",
                    "title": "报警级别",
                },
                "alarm_code": {"type": "string", "title": "报警码"},
                "alarm_message": {"type": "string", "title": "激活文案", "default": "alarm active"},
                "clear_message": {"type": "string", "title": "解除文案", "default": "alarm clear"},
            },
        },
        capability_tags=("rule.decision", "inspection.alarm", "inspection.alarm.condition"),
    ),
    handler=_alarm_condition_handler,
)
