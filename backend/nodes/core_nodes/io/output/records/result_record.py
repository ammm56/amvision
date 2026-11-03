"""工业结果对象输出节点。"""

from __future__ import annotations

from pydantic import ValidationError

from backend.contracts.workflows.inspection import LimitCheckSummary
from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.inspection_record import (
    build_result_record_payload,
    read_optional_reason_input,
    read_optional_value_input,
)
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _result_record_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """组装统一的工业结果对象。"""

    decision_payload = require_value_payload(request.input_values.get("decision"), field_name="decision")
    try:
        decision = LimitCheckSummary.model_validate(decision_payload["value"])
    except ValidationError as exc:
        raise InvalidRequestError(f"decision 需要 Check Limits 的完整三态摘要: {exc}") from exc
    metrics_value = read_optional_value_input(request.input_values.get("metrics"), field_name="metrics")
    reason_value = read_optional_reason_input(request.input_values.get("reason"))
    metadata_value = read_optional_value_input(request.input_values.get("metadata"), field_name="metadata")
    result_payload = build_result_record_payload(
        state=decision.state,
        metrics_value=metrics_value,
        conditions_value=decision.model_dump(mode="json"),
        reason_value=reason_value or decision.reason,
        metadata_value=metadata_value,
        alarm_payload=request.input_values.get("alarm"),
        image_payload=request.input_values.get("image"),
        video_payload=request.input_values.get("video"),
    )
    return {
        "result": result_payload,
        "summary": build_value_payload(
            {
                "state": decision.state,
                "passed": decision.passed,
                "has_reason": "reason" in result_payload,
                "has_metrics": metrics_value is not None,
                "has_conditions": True,
                "has_alarm": "alarm" in result_payload,
                "has_image": "image" in result_payload,
                "has_video": "video" in result_payload,
            }
        ),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.result-record",
        version="1.0.0",
        metadata={"requires_execution_review": True},
        display_name="Result Record",
        category="core.inspection.record",
        description="保留 Check Limits 的完整三态判定、量值、原因和证据；仅 OK 可放行。",
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
