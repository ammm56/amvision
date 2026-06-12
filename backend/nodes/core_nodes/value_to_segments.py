"""value.v1 转 segments.v1 适配节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    require_value_payload,
)
from backend.nodes.core_nodes.segments_to_regions import _require_segments_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _value_to_segments_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把 value.v1 内的 segments 结构恢复为正式 segments.v1。"""

    raw_value = require_value_payload(request.input_values.get("value"), field_name="value")["value"]
    normalized_segments = _require_segments_payload(raw_value, node_id=request.node_id)
    source_image = _resolve_source_image(request, normalized_segments.get("source_image"))
    segment_items = [dict(item) for item in normalized_segments["items"]]
    return {
        "segments": {
            "source_image": source_image,
            "selected_frame_index": normalized_segments.get("selected_frame_index"),
            "count": len(segment_items),
            "items": segment_items,
        },
        "summary": build_value_payload(
            {
                "count": len(segment_items),
                "selected_frame_index": normalized_segments.get("selected_frame_index"),
                "source_image_attached": source_image is not None,
            }
        ),
    }


def _resolve_source_image(
    request: WorkflowNodeExecutionRequest,
    source_image: object,
) -> dict[str, object] | None:
    """优先使用 value 内已有 source_image，否则回退到显式 image 输入。"""

    if isinstance(source_image, dict):
        return require_image_payload(source_image)
    image_input = request.input_values.get("image")
    if image_input is not None:
        return require_image_payload(image_input)
    return None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.value-to-segments",
        display_name="Value To Segments",
        category="logic.transform",
        description="把 value.v1 中的 segments 结构恢复为正式 segments.v1，适合批处理循环体里把逐项 value 输入重新接回分割桥接链。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="segments",
                display_name="Segments",
                payload_type_id="segments.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("logic.transform", "payload.bridge", "segments.bridge"),
    ),
    handler=_value_to_segments_handler,
)
