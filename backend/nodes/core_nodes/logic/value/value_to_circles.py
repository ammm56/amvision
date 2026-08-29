"""value.v1 转 circles.v1 节点。"""

from backend.nodes.core_nodes.support.typed_payload_bridges import (
    build_value_to_payload_node_spec,
    require_circles_payload,
)


CORE_NODE_SPEC = build_value_to_payload_node_spec(
    node_type_id="core.logic.value-to-circles",
    display_name="Value To Circles",
    output_name="circles",
    output_display_name="Circles",
    payload_type_id="circles.v1",
    description="把 value.v1 中的圆检测结果校验并恢复为正式 circles.v1。",
    validator=require_circles_payload,
    capability_tag="circles.bridge",
)
