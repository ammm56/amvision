"""OBBs Batch 到 value List 的桥接节点。"""

from backend.nodes.core_nodes.support.model_batch_bridges import (
    build_model_batch_to_value_list_node_spec,
)
from backend.nodes.core_nodes.support.typed_payload_bridges import require_obbs_payload
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE


CORE_NODE_SPEC = build_model_batch_to_value_list_node_spec(
    node_type_id="core.logic.obbs-batch-to-value-list",
    display_name="OBBs Batch To Value List",
    input_name="obbs_batch",
    input_display_name="OBBs Batch",
    input_payload_type_id="obbs-batch.v1",
    format_id="amvision.obbs-batch.v1",
    task_type=OBB_TASK_TYPE,
    result_payload_type_id="obbs.v1",
    result_validator=require_obbs_payload,
)
