"""本地图像载入节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
    NodeParameterInputBinding,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import (
    build_local_file_summary,
)
from backend.nodes.core_nodes.support.local_io.files import decode_local_image_header
from backend.nodes.core_nodes.support.local_io.reading import (
    DEFAULT_IMAGE_MAX_BYTES,
    DEFAULT_IMAGE_MAX_PIXELS,
    read_local_bytes,
    read_positive_limit,
    resolve_file_source,
)
from backend.nodes.runtime_support import register_image_bytes
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _image_load_local_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """从本地磁盘读取单张图片并注册为 memory image-ref。"""

    image_path, expected = resolve_file_source(request)
    content, record = read_local_bytes(
        image_path,
        expected_record=expected,
        max_bytes=read_positive_limit(
            request.parameters, "max_bytes", DEFAULT_IMAGE_MAX_BYTES
        ),
    )
    image_bytes, media_type, width, height = decode_local_image_header(
        image_path,
        content,
        max_pixels=read_positive_limit(
            request.parameters, "max_pixels", DEFAULT_IMAGE_MAX_PIXELS
        ),
    )
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
            file_record=record,
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
        category="core.io.image",
        description="从本地磁盘读取单张图片，并输出 execution-scoped memory image-ref。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="file",
                display_name="File",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="path",
                display_name="Path",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="local_path", input_port_name="path"
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
                },
                "max_bytes": {
                    "type": "integer",
                    "title": "最大字节数",
                    "minimum": 1,
                    "default": DEFAULT_IMAGE_MAX_BYTES,
                },
                "max_pixels": {
                    "type": "integer",
                    "title": "最大像素数",
                    "minimum": 1,
                    "default": DEFAULT_IMAGE_MAX_PIXELS,
                },
            },
        },
        capability_tags=("io.input", "image.input", "image.memory"),
    ),
    handler=_image_load_local_handler,
)
