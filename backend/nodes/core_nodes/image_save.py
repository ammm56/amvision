"""图片保存节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.runtime_support import copy_image_payload, require_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _image_save_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把输入图片复制到目标 object key。"""

    overwrite = bool(request.parameters.get("overwrite", True))
    object_key = request.parameters.get("object_key")
    normalized_object_key = object_key.strip() if isinstance(object_key, str) and object_key.strip() else None
    saved_payload = copy_image_payload(
        request,
        source_payload=require_image_payload(request.input_values.get("image")),
        object_key=normalized_object_key,
        overwrite=overwrite,
        variant_name="saved",
    )
    return {"image": saved_payload}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-save",
        display_name="Save Image",
        category="io.output",
        description="把图片引用复制到指定 object key，供后续节点或外部接口复用。",
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
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "object_key": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
        },
        capability_tags=("io.output", "image.persist"),
    ),
    handler=_image_save_handler,
)