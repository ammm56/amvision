"""图片预览节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _image_preview_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把图片引用转换成可直接进入 HTTP 响应的结构化 body。"""

    image_payload = require_image_payload(request.input_values.get("image"))
    preview_body: dict[str, object] = {
        "type": "image-preview",
        "image": image_payload,
    }
    title = request.parameters.get("title")
    if isinstance(title, str) and title.strip():
        preview_body["title"] = title.strip()
    return {"body": preview_body}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-preview",
        display_name="Image Preview",
        category="ui.preview",
        description="把图片引用转换成可直接进入 HTTP 响应的预览 body。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
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
                "title": {"type": "string"},
            },
        },
        capability_tags=("ui.preview", "response.body"),
    ),
    handler=_image_preview_handler,
)