"""Categories Batch 到完整关联项 List 的转换节点。"""

from backend.nodes.core_nodes.support.model_batch_items import (
    build_model_batch_to_items_node_spec,
)
from backend.nodes.core_nodes.support.typed_payload_bridges import (
    require_categories_payload,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE


CORE_NODE_SPEC = build_model_batch_to_items_node_spec(
    node_type_id="core.logic.categories-batch-to-items",
    display_name="Categories Batch To Items",
    input_name="categories_batch",
    input_display_name="Categories Batch",
    input_payload_type_id="categories-batch.v1",
    format_id="amvision.categories-batch.v1",
    task_type=CLASSIFICATION_TASK_TYPE,
    result_payload_type_id="categories.v1",
    result_validator=require_categories_payload,
)
