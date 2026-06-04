"""本地图像载入节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._local_io_node_support import (
    build_local_file_summary,
    read_local_image_file,
    resolve_local_file_path_from_request,
)
from backend.nodes.runtime_support import register_image_bytes
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _image_load_local_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从本地磁盘读取单张图片并注册为 memory image-ref。"""

    image_path = resolve_local_file_path_from_request(
        request,
        parameter_name="local_path",
        description="本地图像文件",
    )
    image_bytes, media_type, width, height = read_local_image_file(image_path)
    return {
        "image": register_image_bytes(
            request,
            content=image_bytes,
            media_type=media_type,
            width=width,
            height=height,
        ),
        "summary": build_local_file_summary(
            local_path=image_path,
            extra_fields={
                "media_type": media_type,
                "width": width,
                "height": height,
            },
        ),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-load-local",
        display_name="Load Local Image",
        category="io.input",
        description="从本地磁盘读取单张图片，并输出 execution-scoped memory image-ref。",
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
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
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
                    "title": "本地图像路径",
                    "description": "可直接填写本机图片绝对路径，也可以通过 Path 输入端口动态传入。",
                }
            },
        },
        capability_tags=("io.input", "image.input", "image.memory"),
    ),
    handler=_image_load_local_handler,
)
