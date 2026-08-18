"""正式视频响应 body 节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.video_runtime_support import build_response_video_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _video_body_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把视频引用转换成正式 response-body.v1 视频结构。"""

    save_location = request.parameters.get("save_location")
    normalized_save_location = (
        save_location.strip()
        if isinstance(save_location, str) and save_location.strip()
        else None
    )
    response_video = build_response_video_payload(
        request,
        video_payload=request.input_values.get("video"),
        save_location=normalized_save_location,
        variant_name="response-video",
    )
    response_body: dict[str, object] = {
        "type": "video",
        "video": response_video,
    }
    title = request.parameters.get("title")
    if isinstance(title, str) and title.strip():
        response_body["title"] = title.strip()
    return {"body": response_body}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.video-body",
        display_name="Video Body",
        category="core.io.response",
        description="把视频引用转换成正式 response-body.v1 视频结构，供 workflow app 返回可播放视频结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="video",
                display_name="Video",
                payload_type_id="video-ref.v1",
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
                    "description": "正式视频 body 的显示名称。",
                    "default": "Video",
                },
                "save_location": {
                    "type": "string",
                    "title": "保存位置",
                    "description": "可选保存位置；相对路径写入 ObjectStore，绝对路径写入本地磁盘。",
                    "default": "",
                },
            },
        },
        capability_tags=("integration.output", "response.body", "video"),
    ),
    handler=_video_body_handler,
)
