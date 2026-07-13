"""value 转 image-ref.v1 节点。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, extract_value_by_path, require_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "value-to-image-ref"


def _value_to_image_ref_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 value.v1 中保存的 image-ref 对象恢复成正式 image-ref.v1。"""

    value_root = require_value_payload(request.input_values.get("value"), field_name="value")["value"]
    raw_path = request.parameters.get("path")
    image_candidate = value_root if is_empty_parameter(raw_path) else extract_value_by_path(root=value_root, path=_read_path(raw_path))
    if not isinstance(image_candidate, dict):
        raise InvalidRequestError(
            f"{NODE_NAME} 节点提取到的 image-ref 必须是对象",
            details={"node_id": request.node_id},
        )
    image_payload = require_image_payload(image_candidate)
    return {
        "image": image_payload,
        "summary": build_value_payload(
            {
                "transport_kind": image_payload.get("transport_kind"),
                "media_type": image_payload.get("media_type"),
                "width": image_payload.get("width"),
                "height": image_payload.get("height"),
                "image_handle": image_payload.get("image_handle"),
                "object_key": image_payload.get("object_key"),
            }
        ),
    }


def _read_path(raw_value: object) -> str:
    """读取非空点分路径参数。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{NODE_NAME} 节点的 path 必须是非空字符串")
    return raw_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.value-to-image-ref",
        display_name="Value To Image Ref",
        category="logic.transform",
        description="把 value.v1 中的 image-ref 对象恢复为正式 image-ref.v1，适合 for-each 逐图推理、逐图预览和逐图 OpenCV 处理。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
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
                "path": {
                    "type": "string",
                    "title": "Path",
                    "description": "可选点分路径；为空时直接把 value.value 当作 image-ref 对象。",
                },
            },
        },
        capability_tags=("logic.transform", "image.ref", "logic.iteration"),
    ),
    handler=_value_to_image_ref_handler,
)
