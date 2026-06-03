"""工业结果对象输出节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.nodes.video_runtime_support import require_video_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _result_record_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """组装统一的工业结果对象。"""

    decision_payload = require_value_payload(request.input_values.get("decision"), field_name="decision")
    ok_ng = _require_ok_ng(decision_payload["value"])
    metrics_value = _read_optional_value_input(request.input_values.get("metrics"), field_name="metrics")
    conditions_value = _read_optional_value_input(request.input_values.get("conditions"), field_name="conditions")
    reason_value = _read_optional_reason_input(request.input_values.get("reason"))
    metadata_value = _read_optional_value_input(request.input_values.get("metadata"), field_name="metadata")
    result_payload: dict[str, object] = {
        "ok_ng": ok_ng,
        "ok": ok_ng == "OK",
    }
    if reason_value is not None:
        result_payload["reason"] = reason_value
    if metrics_value is not None:
        result_payload["metrics"] = metrics_value
    if conditions_value is not None:
        result_payload["conditions"] = conditions_value
    if metadata_value is not None:
        result_payload["metadata"] = metadata_value
    if request.input_values.get("image") is not None:
        result_payload["image"] = require_image_payload(request.input_values.get("image"))
    if request.input_values.get("video") is not None:
        result_payload["video"] = require_video_payload(request.input_values.get("video"))
    return {
        "result": result_payload,
        "summary": build_value_payload(
            {
                "ok_ng": ok_ng,
                "has_reason": reason_value is not None,
                "has_metrics": metrics_value is not None,
                "has_conditions": conditions_value is not None,
                "has_image": "image" in result_payload,
                "has_video": "video" in result_payload,
            }
        ),
    }


def _require_ok_ng(raw_value: object) -> str:
    """校验 decision 输入。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError("result-record 节点的 decision 输入必须是字符串")
    normalized_value = raw_value.strip().upper()
    if normalized_value not in {"OK", "NG"}:
        raise InvalidRequestError("result-record 节点的 decision 输入仅支持 OK 或 NG")
    return normalized_value


def _read_optional_value_input(raw_payload: object, *, field_name: str) -> object | None:
    """读取可选 value.v1 输入。"""

    if raw_payload is None:
        return None
    return require_value_payload(raw_payload, field_name=field_name)["value"]


def _read_optional_reason_input(raw_payload: object) -> str | None:
    """读取可选 reason 输入。"""

    if raw_payload is None:
        return None
    reason_value = require_value_payload(raw_payload, field_name="reason")["value"]
    if not isinstance(reason_value, str) or not reason_value.strip():
        raise InvalidRequestError("result-record 节点的 reason 输入必须是非空字符串")
    return reason_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.result-record",
        display_name="Result Record",
        category="inspection.output",
        description="组装统一的工业结果对象，包含 OK/NG、reason、metrics、conditions 和 image/video 引用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="decision",
                display_name="Decision",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="conditions",
                display_name="Conditions",
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
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("inspection.output", "inspection.result", "integration.output"),
    ),
    handler=_result_record_handler,
)
