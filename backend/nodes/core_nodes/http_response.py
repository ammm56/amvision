"""HTTP 响应节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _http_response_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把结构化 body 包装为标准 http-response payload。"""

    body_payload = request.input_values.get("body")
    if not isinstance(body_payload, dict):
        body_payload = {"value": body_payload}
    status_code = request.parameters.get("status_code", 200)
    normalized_status_code = int(status_code) if isinstance(status_code, (int, float, str)) else 200
    return {
        "response": {
            "status_code": normalized_status_code,
            "body": body_payload,
        }
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.http-response",
        display_name="HTTP Response",
        category="integration.output",
        description="把结构化 body 包装成标准 http-response payload。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="response",
                display_name="Response",
                payload_type_id="http-response.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "status_code": {"type": "integer", "minimum": 100, "maximum": 599},
            },
        },
        capability_tags=("integration.output", "http.response"),
    ),
    handler=_http_response_handler,
)