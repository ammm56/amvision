"""标准响应包体节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _response_envelope_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把业务数据包装成固定的 response-body.v1 envelope。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含标准 envelope body 的节点输出。
    """

    body: dict[str, object] = {
        "code": _read_response_code(request.parameters.get("code")),
        "message": _read_response_message(
            input_payload=request.input_values.get("message"),
            default_message=request.parameters.get("message"),
            node_id=request.node_id,
        ),
        "data": _read_optional_input_value(
            request.input_values.get("data"),
            field_name="data",
        ),
    }
    meta_value = _read_optional_input_value(
        request.input_values.get("meta"),
        field_name="meta",
    )
    if meta_value is not None:
        body["meta"] = meta_value
    return {"body": body}


def _read_response_code(raw_value: object) -> int:
    """读取 response-envelope 的静态 code。"""

    if raw_value is None:
        return 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("response-envelope 节点的 code 参数必须是整数")
    return raw_value


def _read_response_message(*, input_payload: object, default_message: object, node_id: str) -> str:
    """读取 response-envelope 的消息文本。

    参数：
    - input_payload：可选的 message 输入 payload。
    - default_message：参数中的默认消息文本。
    - node_id：当前节点 id。

    返回：
    - str：最终用于 envelope 的消息文本。
    """

    if input_payload is not None:
        message_value = require_value_payload(input_payload, field_name="message")["value"]
        if not isinstance(message_value, str) or not message_value.strip():
            raise InvalidRequestError(
                "response-envelope 节点的 message 输入必须是非空字符串",
                details={"node_id": node_id},
            )
        return message_value.strip()
    if default_message is None:
        return "ok"
    if not isinstance(default_message, str) or not default_message.strip():
        raise InvalidRequestError("response-envelope 节点的 message 参数必须是非空字符串")
    return default_message.strip()


def _read_optional_input_value(raw_payload: object, *, field_name: str) -> object:
    """读取可选 value.v1 输入。"""

    if raw_payload is None:
        return None
    return require_value_payload(raw_payload, field_name=field_name)["value"]


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.response-envelope",
        display_name="Response Envelope",
        category="integration.output",
        description="把 data、message、meta 组装成标准 response-body.v1 envelope。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="data",
                display_name="Data",
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
                name="meta",
                display_name="Meta",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "code": {"type": "integer"},
                "message": {"type": "string", "minLength": 1},
            },
        },
        capability_tags=("integration.output", "response.body"),
    ),
    handler=_response_envelope_handler,
)