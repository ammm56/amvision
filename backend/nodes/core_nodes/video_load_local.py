"""本地视频载入节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.video_runtime_support import (
    build_local_video_payload,
    probe_video_metadata_with_backend,
    read_video_tool_summary,
    resolve_video_path_from_request,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _video_load_local_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从本地磁盘读取视频路径并返回 video-ref。"""

    video_path = resolve_video_path_from_request(request)
    metadata, probe_backend = probe_video_metadata_with_backend(video_path)
    video_payload = build_local_video_payload(local_path=str(video_path), metadata=metadata)
    tool_summary = read_video_tool_summary()
    return {
        "video": video_payload,
        "summary": build_value_payload(
            {
                "local_path": str(video_path),
                "probe_backend": probe_backend,
                **tool_summary,
                "frame_count": metadata["frame_count"],
                "fps": metadata["fps"],
                "width": metadata["width"],
                "height": metadata["height"],
                "duration_ms": metadata["duration_ms"],
            }
        ),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.video-load-local",
        display_name="Load Local Video",
        category="io.video",
        description="从本地磁盘读取视频文件路径，并输出带基础元数据的 video-ref.v1。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="path",
                display_name="Path",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="video",
                display_name="Video",
                payload_type_id="video-ref.v1",
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
                "local_path": {
                    "type": "string",
                    "title": "本地视频路径",
                    "description": "可直接填本机视频绝对路径，也可以从 path 输入端口动态传入。",
                }
            },
        },
        capability_tags=("io.video", "video.input"),
    ),
    handler=_video_load_local_handler,
)
