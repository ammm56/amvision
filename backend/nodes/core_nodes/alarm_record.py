"""工业报警对象输出节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    require_boolean_payload,
    require_value_payload,
)
from backend.nodes.runtime_support import require_image_payload
from backend.nodes.video_runtime_support import require_video_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _alarm_record_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """组装统一的工业报警对象。"""

    active_payload = require_boolean_payload(request.input_values.get("active"), field_name="active")
    alarm_level = _read_alarm_level(request.parameters.get("alarm_level"))
    alarm_code = _read_optional_code(request.parameters.get("alarm_code"))
    message_value = _read_message(request)
    metrics_value = _read_optional_value_input(request.input_values.get("metrics"), field_name="metrics")
    metadata_value = _read_optional_value_input(request.input_values.get("metadata"), field_name="metadata")
    alarm_payload: dict[str, object] = {
        "active": active_payload["value"],
        "level": alarm_level,
        "message": message_value,
    }
    if alarm_code is not None:
        alarm_payload["code"] = alarm_code
    if metrics_value is not None:
        alarm_payload["metrics"] = metrics_value
    if metadata_value is not None:
        alarm_payload["metadata"] = metadata_value
    if request.input_values.get("image") is not None:
        alarm_payload["image"] = require_image_payload(request.input_values.get("image"))
    if request.input_values.get("video") is not None:
        alarm_payload["video"] = require_video_payload(request.input_values.get("video"))
    return {
        "alarm": alarm_payload,
        "summary": build_value_payload(
            {
                "active": active_payload["value"],
                "level": alarm_level,
                "code": alarm_code,
                "has_metrics": metrics_value is not None,
                "has_image": "image" in alarm_payload,
                "has_video": "video" in alarm_payload,
            }
        ),
    }


def _read_alarm_level(raw_value: object) -> str:
    """读取报警级别。"""

    if raw_value is None:
        return "warning"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("alarm-record 的 alarm_level 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"info", "warning", "error", "critical"}:
        raise InvalidRequestError("alarm-record 的 alarm_level 仅支持 info/warning/error/critical")
    return normalized_value


def _read_optional_code(raw_value: object) -> str | None:
    """读取可选报警码。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("alarm-record 的 alarm_code 必须是非空字符串")
    return raw_value.strip()


def _read_message(request: WorkflowNodeExecutionRequest) -> str:
    """读取报警文案。"""

    message_input = request.input_values.get("message")
    if message_input is not None:
        message_value = require_value_payload(message_input, field_name="message")["value"]
    else:
        message_value = request.parameters.get("alarm_message")
    if not isinstance(message_value, str) or not message_value.strip():
        raise InvalidRequestError("alarm-record 要求 message 输入或 alarm_message 参数为非空字符串")
    return message_value.strip()


def _read_optional_value_input(raw_payload: object, *, field_name: str) -> object | None:
    """读取可选 value.v1 输入。"""

    if raw_payload is None:
        return None
    return require_value_payload(raw_payload, field_name=field_name)["value"]


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.alarm-record",
        display_name="Alarm Record",
        category="inspection.output",
        description="组装统一的工业报警对象，包含激活状态、级别、报警码、文案和可选 image/video 引用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="active",
                display_name="Active",
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
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "alarm_level": {
                    "type": "string",
                    "title": "报警级别",
                    "enum": ["info", "warning", "error", "critical"],
                    "default": "warning",
                },
                "alarm_code": {"type": "string", "title": "报警码"},
                "alarm_message": {"type": "string", "title": "默认报警文案"},
            },
        },
        capability_tags=("inspection.output", "inspection.alarm", "integration.output"),
    ),
    handler=_alarm_record_handler,
)
