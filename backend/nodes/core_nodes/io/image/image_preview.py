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
    RESPONSE_IMAGE_TRANSPORT_STORAGE_REF,
    build_response_image_payload,
    require_image_payload,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.preview_display_outputs import (
    build_preview_run_artifact_object_key,
    read_preview_run_id,
)


def _image_preview_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把图片引用转换成可直接进入 HTTP 响应的结构化 body。"""

    output_object_key = request.parameters.get("output_object_key")
    normalized_output_object_key = (
        output_object_key.strip()
        if isinstance(output_object_key, str) and output_object_key.strip()
        else None
    )
    response_transport_mode = str(request.parameters.get("response_transport_mode", "inline-base64")).strip()
    if response_transport_mode == RESPONSE_IMAGE_TRANSPORT_STORAGE_REF and normalized_output_object_key is None:
        normalized_output_object_key = _build_preview_artifact_object_key(request)
    response_image = build_response_image_payload(
        request,
        image_payload=request.input_values.get("image"),
        response_transport_mode=response_transport_mode,
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


def _build_preview_artifact_object_key(request: WorkflowNodeExecutionRequest) -> str | None:
    """为 storage-ref Preview Run 自动生成受生命周期管理的 artifact 路径。

    参数：
    - request：当前 Image Preview 节点执行请求。

    返回：
    - str | None：存在 Preview Run 上下文时返回 artifact object key，否则返回 None。
    """

    preview_run_id = read_preview_run_id(request.execution_metadata)
    if preview_run_id is None:
        return None
    image_payload = require_image_payload(request.input_values.get("image"))
    return build_preview_run_artifact_object_key(
        preview_run_id=preview_run_id,
        node_id=request.node_id,
        artifact_name="image-preview",
        media_type=str(image_payload.get("media_type") or "image/png"),
    )


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
                "title": {
                    "type": "string",
                    "title": "标题",
                    "description": "图片预览卡片显示名称。",
                    "default": "Image Preview",
                },
                "response_transport_mode": {
                    "type": "string",
                    "title": "返回方式",
                    "description": "inline-base64 只随本次 Preview Run 返回；storage-ref 保存为受 Preview Run 生命周期管理的 artifact。",
                    "enum": ["inline-base64", "storage-ref"],
                    "default": "inline-base64",
                },
                "output_object_key": {
                    "type": "string",
                    "title": "输出 object_key",
                    "description": "仅 storage-ref 模式使用；为空时自动保存到 Preview Run artifact 目录。",
                    "default": "",
                },
            },
        },
        capability_tags=("ui.preview", "response.body"),
    ),
    handler=_image_preview_handler,
)