"""value.v1 转 poses.v1 节点。"""

from backend.nodes.core_nodes.support.typed_payload_bridges import (
    build_value_to_payload_node_spec,
    require_poses_payload,
)


CORE_NODE_SPEC = build_value_to_payload_node_spec(
    node_type_id="core.logic.value-to-poses",
    display_name="Value To Poses",
    output_name="poses",
    output_display_name="Poses",
    payload_type_id="poses.v1",
    description="把 value.v1 中的姿态结果校验并恢复为正式 poses.v1。",
    validator=require_poses_payload,
    capability_tag="poses.bridge",
)
