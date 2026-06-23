"""本地输出节点输入解析 helper。"""

from __future__ import annotations

import json

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def resolve_value_or_result_input(
    request: WorkflowNodeExecutionRequest,
    *,
    value_input_name: str = "value",
    result_input_name: str = "result",
    alarm_input_name: str = "alarm",
) -> tuple[object, str]:
    """读取 value、result-record 或 alarm-record 输入，且要求三选一。"""

    value_input = request.input_values.get(value_input_name)
    result_input = request.input_values.get(result_input_name)
    alarm_input = request.input_values.get(alarm_input_name)
    provided_count = sum(
        1
        for item in (value_input, result_input, alarm_input)
        if item is not None
    )
    if provided_count != 1:
        raise InvalidRequestError(
            "节点要求三选一提供 value、result 或 alarm 输入",
            details={
                "node_id": request.node_id,
                "value_input_name": value_input_name,
                "result_input_name": result_input_name,
                "alarm_input_name": alarm_input_name,
            },
        )
    if value_input is not None:
        return require_value_payload(value_input, field_name=value_input_name)["value"], "value"
    if result_input is not None:
        if not isinstance(result_input, dict):
            raise InvalidRequestError(
                "result 输入必须是对象",
                details={"node_id": request.node_id, "input_name": result_input_name},
            )
        return json.loads(json.dumps(result_input, ensure_ascii=False)), "result-record"
    if not isinstance(alarm_input, dict):
        raise InvalidRequestError(
            "alarm 输入必须是对象",
            details={"node_id": request.node_id, "input_name": alarm_input_name},
        )
    return json.loads(json.dumps(alarm_input, ensure_ascii=False)), "alarm-record"
