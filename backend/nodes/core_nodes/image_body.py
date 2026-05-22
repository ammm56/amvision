"""正式图片响应 body 节点。"""

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


def _image_body_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把图片引用转换成正式 response-body.v1 图片结构。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 body 输出的正式图片响应。
    """

    output_object_key = request.parameters.get("output_object_key")
    normalized_output_object_key = (
        output_object_key.strip()
        if isinstance(output_object_key, str) and output_object_key.strip()
        else None
    )
    response_transport_mode = str(
        request.parameters.get("response_transport_mode", "inline-base64")
    ).strip()
    response_image = build_response_image_payload(
        request,
        image_payload=request.input_values.get("image"),
        response_transport_mode=response_transport_mode,
        object_key=normalized_output_object_key,
        variant_name="response-image",
    )
    response_body: dict[str, object] = {
        "type": "image",
        "image": response_image,
    }
    title = request.parameters.get("title")
    if isinstance(title, str) and title.strip():
        response_body["title"] = title.strip()
    return {"body": response_body}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.image-body",
        display_name="Image Body",
        category="integration.output",
        description="把图片引用转换成正式 response-body.v1 图片结构。",
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
                    "description": "正式图片 body 的显示名称。",
                    "default": "Image",
                },
                "response_transport_mode": {
                    "type": "string",
                    "title": "返回方式",
                    "description": "inline-base64 直接返回图片 base64；storage-ref 返回稳定 object_key 引用。",
                    "enum": ["inline-base64", "storage-ref"],
                    "default": "inline-base64",
                },
                "output_object_key": {
                    "type": "string",
                    "title": "输出 object_key",
                    "description": "仅 storage-ref 模式使用；为空时优先复用输入存储路径，或按 runtime 默认目录生成。",
                    "default": "",
                },
            },
        },
        capability_tags=("integration.output", "response.body", "image"),
    ),
    handler=_image_body_handler,
)