"""deployment segmentation Batch 节点。"""

from backend.nodes.core_nodes.support.deployment_batch import (
    build_deployment_batch_node_spec,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE


CORE_NODE_SPEC = build_deployment_batch_node_spec(
    node_type_id="core.model.segmentation-batch",
    display_name="Segmentation Batch",
    task_type=SEGMENTATION_TASK_TYPE,
    output_name="segments_batch",
    output_display_name="Segments Batch",
    output_payload_type_id="segments-batch.v1",
    format_id="amvision.segments-batch.v1",
)
