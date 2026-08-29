"""value.v1 转 categories.v1 节点。"""

from backend.nodes.core_nodes.support.typed_payload_bridges import (
    build_value_to_payload_node_spec,
    require_categories_payload,
)


CORE_NODE_SPEC = build_value_to_payload_node_spec(
    node_type_id="core.logic.value-to-categories",
    display_name="Value To Categories",
    output_name="categories",
    output_display_name="Categories",
    payload_type_id="categories.v1",
    description="把 value.v1 中的分类结果校验并恢复为正式 categories.v1。",
    validator=require_categories_payload,
    capability_tag="categories.bridge",
)
