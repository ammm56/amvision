"""deployment OBB Batch 节点。"""

from backend.nodes.core_nodes.support.deployment_batch import (
    build_deployment_batch_node_spec,
)
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE


CORE_NODE_SPEC = build_deployment_batch_node_spec(
    node_type_id="core.model.obb-batch",
    display_name="OBB Batch",
    task_type=OBB_TASK_TYPE,
    output_name="obbs_batch",
    output_display_name="OBBs Batch",
    output_payload_type_id="obbs-batch.v1",
    format_id="amvision.obbs-batch.v1",
)
