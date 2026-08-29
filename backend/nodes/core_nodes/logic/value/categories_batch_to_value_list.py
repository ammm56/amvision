"""Categories Batch 到 value List 的桥接节点。"""

from backend.nodes.core_nodes.support.model_batch_bridges import (
    build_model_batch_to_value_list_node_spec,
)
from backend.nodes.core_nodes.support.typed_payload_bridges import (
    require_categories_payload,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE


CORE_NODE_SPEC = build_model_batch_to_value_list_node_spec(
    node_type_id="core.logic.categories-batch-to-value-list",
    display_name="Categories Batch To Value List",
    input_name="categories_batch",
    input_display_name="Categories Batch",
    input_payload_type_id="categories-batch.v1",
    format_id="amvision.categories-batch.v1",
    task_type=CLASSIFICATION_TASK_TYPE,
    result_payload_type_id="categories.v1",
    result_validator=require_categories_payload,
)
