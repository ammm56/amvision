"""value.v1 转 detections.v1 节点。"""

from backend.nodes.core_nodes.support.typed_payload_bridges import (
    build_value_to_payload_node_spec,
    require_detections_payload,
)


CORE_NODE_SPEC = build_value_to_payload_node_spec(
    node_type_id="core.logic.value-to-detections",
    display_name="Value To Detections",
    output_name="detections",
    output_display_name="Detections",
    payload_type_id="detections.v1",
    description="把 value.v1 中的检测结果校验并恢复为正式 detections.v1。",
    validator=require_detections_payload,
    capability_tag="detections.bridge",
)
