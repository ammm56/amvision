"""图片预览节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.runtime_support import build_response_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _image_preview_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把图片引用转换成可直接进入 HTTP 响应的结构化 body。"""

    output_object_key = request.parameters.get("output_object_key")
    normalized_output_object_key = (
        output_object_key.strip()
        if isinstance(output_object_key, str) and output_object_key.strip()
        else None
    )
    response_image = build_response_image_payload(
        request,
        image_payload=request.input_values.get("image"),
        response_transport_mode=str(request.parameters.get("response_transport_mode", "inline-base64")),
        object_key=normalized_output_object_key,
        variant_name="image-preview",
    )
    preview_body: dict[str, object] = {
        "type": "image-preview",
        "image": response_image,
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
                "response_transport_mode": {
                    "type": "string",
                    "enum": ["inline-base64", "storage-ref"],
                },
                "output_object_key": {"type": "string"},
            },
        },
        capability_tags=("ui.preview", "response.body"),
    ),
    handler=_image_preview_handler,
)