"""value.v1 转 obbs.v1 节点。"""

from backend.nodes.core_nodes.support.typed_payload_bridges import (
    build_value_to_payload_node_spec,
    require_obbs_payload,
)


CORE_NODE_SPEC = build_value_to_payload_node_spec(
    node_type_id="core.logic.value-to-obbs",
    display_name="Value To OBBs",
    output_name="obbs",
    output_display_name="OBBs",
    payload_type_id="obbs.v1",
    description="把 value.v1 中的旋转框结果校验并恢复为正式 obbs.v1。",
    validator=require_obbs_payload,
    capability_tag="obbs.bridge",
)
