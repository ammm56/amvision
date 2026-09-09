"""图片预览节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.runtime_support import (
    build_preview_response_image_payload,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _image_preview_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把图片引用转换成可直接进入 HTTP 响应的结构化 body。"""

    save_location = request.parameters.get("save_location")
    response_transport_mode = str(request.parameters.get("response_transport_mode", "inline-base64")).strip()
    response_image = build_preview_response_image_payload(
        request,
        image_payload=request.input_values.get("image"),
        response_transport_mode=response_transport_mode,
        object_key=None,
        save_location=save_location if isinstance(save_location, str) else None,
        display_object_key=None,
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
        category="core.ui.preview",
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
                "title": {
                    "type": "string",
                    "title": "标题",
                    "description": "图片预览卡片显示名称。",
                    "default": "Image Preview",
                },
                "response_transport_mode": {
                    "type": "string",
                    "title": "返回方式",
                    "description": "正式响应可返回 inline-base64 或 storage-ref；编辑器预览统一使用内存显示，保存位置单独控制持久化。",
                    "enum": ["inline-base64", "storage-ref"],
                    "default": "inline-base64",
                },
                "save_location": {
                    "type": "string",
                    "title": "保存位置",
                    "description": "可选保存位置；相对路径写入 ObjectStore，绝对路径写入本地磁盘。",
                    "default": "",
                },
            },
        },
        capability_tags=("ui.preview", "response.body"),
    ),
    handler=_image_preview_handler,
)
