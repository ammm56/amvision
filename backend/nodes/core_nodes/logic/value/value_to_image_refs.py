"""value.v1 转 image-refs.v1 节点。"""

from backend.nodes.core_nodes.support.typed_payload_bridges import (
    build_value_to_payload_node_spec,
    require_image_refs_payload,
)


CORE_NODE_SPEC = build_value_to_payload_node_spec(
    node_type_id="core.logic.value-to-image-refs",
    display_name="Value To Image Refs",
    output_name="images",
    output_display_name="Images",
    payload_type_id="image-refs.v1",
    description="把 value.v1 中的 image-ref 数组或 image-refs 对象恢复为正式 image-refs.v1，不复制图片主体。",
    validator=require_image_refs_payload,
    capability_tag="image.refs.bridge",
)
