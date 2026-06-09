"""统一 workflow 结果对象节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._batch_result_summary_node_support import (
    clone_inline_json_value,
)
from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "workflow-result"
SUPPORTED_WORKFLOW_STATUSES = {"succeeded", "failed", "accepted", "partial"}


def _workflow_result_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把业务结果包装成统一 workflow-result.v1。"""

    status = _read_status(
        request.input_values.get("status"),
        parameter_value=request.parameters.get("status"),
    )
    code = _read_code(
        request.input_values.get("code"),
        parameter_value=request.parameters.get("code"),
    )
    message = _read_message(
        request.input_values.get("message"),
        parameter_value=request.parameters.get("message"),
        status=status,
    )
    data_value, data_source = _read_optional_data_value(request)
    metrics_value = _read_optional_value_input(request.input_values.get("metrics"), field_name="metrics")
    files_value = _read_optional_value_input(request.input_values.get("files"), field_name="files")
    metadata_value = _read_optional_object_input(request.input_values.get("metadata"), field_name="metadata")

    trace_id, trace_source = _read_optional_text_value(
        request.input_values.get("trace_id"),
        field_name="trace_id",
        parameter_value=request.parameters.get("trace_id"),
        fallback_value=_read_execution_trace_id(request),
        fallback_source="execution_metadata.trace_id",
    )
    event_id, event_source = _read_optional_text_value(
        request.input_values.get("event_id"),
        field_name="event_id",
        parameter_value=request.parameters.get("event_id"),
        fallback_value=_read_execution_event_id(request),
        fallback_source="execution_metadata.trigger_event_id",
    )

    workflow_result: dict[str, object] = {
        "status": status,
        "code": code,
        "message": message,
    }
    if data_value is not None:
        workflow_result["data"] = data_value
    if metrics_value is not None:
        workflow_result["metrics"] = metrics_value
    if files_value is not None:
        workflow_result["files"] = files_value
    if trace_id is not None:
        workflow_result["trace_id"] = trace_id
    if event_id is not None:
        workflow_result["event_id"] = event_id
    if metadata_value is not None:
        workflow_result["metadata"] = metadata_value

    return {
        "workflow_result": workflow_result,
        "summary": build_value_payload(
            {
                "status": status,
                "code": code,
                "data_source": data_source,
                "trace_source": trace_source,
                "event_source": event_source,
                "has_data": data_value is not None,
                "has_metrics": metrics_value is not None,
                "has_files": files_value is not None,
                "has_trace_id": trace_id is not None,
                "has_event_id": event_id is not None,
                "has_metadata": metadata_value is not None,
            }
        ),
    }


def _read_status(input_payload: object, *, parameter_value: object) -> str:
    """读取 workflow 状态。"""

    raw_value = parameter_value
    if input_payload is not None:
        raw_value = require_value_payload(input_payload, field_name="status")["value"]
    if raw_value is None:
        return "succeeded"
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 的 status 必须是非空字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in SUPPORTED_WORKFLOW_STATUSES:
        raise InvalidRequestError(
            f"{NODE_NAME} 的 status 仅支持 succeeded/failed/accepted/partial"
        )
    return normalized_value


def _read_code(input_payload: object, *, parameter_value: object) -> int:
    """读取 workflow 结果码。"""

    raw_value = parameter_value
    if input_payload is not None:
        raw_value = require_value_payload(input_payload, field_name="code")["value"]
    if raw_value is None:
        return 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{NODE_NAME} 的 code 必须是整数")
    return raw_value


def _read_message(input_payload: object, *, parameter_value: object, status: str) -> str:
    """读取 workflow 消息文本。"""

    raw_value = parameter_value
    if input_payload is not None:
        raw_value = require_value_payload(input_payload, field_name="message")["value"]
    if raw_value is None:
        return "ok" if status == "succeeded" else status
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 的 message 必须是非空字符串")
    return raw_value.strip()


def _read_optional_data_value(
    request: WorkflowNodeExecutionRequest,
) -> tuple[object | None, str | None]:
    """读取统一 data 字段。"""

    data_payload = request.input_values.get("data")
    result_payload = request.input_values.get("result")
    if data_payload is not None and result_payload is not None:
        raise InvalidRequestError(f"{NODE_NAME} 的 data 和 result 不能同时提供")
    if result_payload is not None:
        if not isinstance(result_payload, dict):
            raise InvalidRequestError(f"{NODE_NAME} 的 result 输入必须是对象")
        return clone_inline_json_value(result_payload), "input.result"
    if data_payload is None:
        return None, None
    return clone_inline_json_value(
        require_value_payload(data_payload, field_name="data")["value"]
    ), "input.data"


def _read_optional_value_input(raw_payload: object, *, field_name: str) -> object | None:
    """读取可选 value.v1 输入。"""

    if raw_payload is None:
        return None
    return clone_inline_json_value(
        require_value_payload(raw_payload, field_name=field_name)["value"]
    )


def _read_optional_object_input(
    raw_payload: object,
    *,
    field_name: str,
) -> dict[str, object] | None:
    """读取可选对象类型 value.v1 输入。"""

    if raw_payload is None:
        return None
    raw_value = require_value_payload(raw_payload, field_name=field_name)["value"]
    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"{NODE_NAME} 的 {field_name}.value 必须是对象")
    return clone_inline_json_value(raw_value)


def _read_optional_text_value(
    input_payload: object,
    *,
    field_name: str,
    parameter_value: object,
    fallback_value: str | None,
    fallback_source: str,
) -> tuple[str | None, str | None]:
    """读取可选文本字段，并返回来源。"""

    raw_value = parameter_value
    source = "parameter"
    if input_payload is not None:
        raw_value = require_value_payload(input_payload, field_name=field_name)["value"]
        source = f"input.{field_name}"
    elif raw_value is None and fallback_value is not None:
        raw_value = fallback_value
        source = fallback_source
    if raw_value is None:
        return None, None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 的 {field_name} 必须是非空字符串")
    return raw_value.strip(), source


def _read_execution_trace_id(request: WorkflowNodeExecutionRequest) -> str | None:
    """从执行元数据读取可选 trace_id。"""

    trace_id = request.execution_metadata.get("trace_id")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    workflow_run_id = request.execution_metadata.get("workflow_run_id")
    if isinstance(workflow_run_id, str) and workflow_run_id.strip():
        return workflow_run_id.strip()
    return None


def _read_execution_event_id(request: WorkflowNodeExecutionRequest) -> str | None:
    """从执行元数据读取可选 event_id。"""

    event_id = request.execution_metadata.get("event_id")
    if isinstance(event_id, str) and event_id.strip():
        return event_id.strip()
    trigger_event_id = request.execution_metadata.get("trigger_event_id")
    if isinstance(trigger_event_id, str) and trigger_event_id.strip():
        return trigger_event_id.strip()
    return None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.workflow-result",
        display_name="Workflow Result",
        category="integration.output",
        description="把 status、code、message、data、metrics、files、trace_id 和 event_id 收成统一 workflow-result 对象。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="status",
                display_name="Status",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="code",
                display_name="Code",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="message",
                display_name="Message",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="data",
                display_name="Data",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="result-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="files",
                display_name="Files",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="trace_id",
                display_name="Trace ID",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="event_id",
                display_name="Event ID",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="metadata",
                display_name="Metadata",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="workflow_result",
                display_name="Workflow Result",
                payload_type_id="workflow-result.v1",
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
                "status": {
                    "type": "string",
                    "enum": ["succeeded", "failed", "accepted", "partial"],
                    "default": "succeeded",
                    "title": "状态",
                },
                "code": {
                    "type": "integer",
                    "title": "结果码",
                    "default": 0,
                },
                "message": {
                    "type": "string",
                    "minLength": 1,
                    "title": "消息",
                },
                "trace_id": {
                    "type": "string",
                    "minLength": 1,
                    "title": "Trace ID",
                },
                "event_id": {
                    "type": "string",
                    "minLength": 1,
                    "title": "Event ID",
                },
            },
        },
        capability_tags=("integration.output", "workflow.result"),
    ),
    handler=_workflow_result_handler,
)
