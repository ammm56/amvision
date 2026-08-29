"""deployment detection Batch 节点。"""

from backend.nodes.core_nodes.support.deployment_batch import (
    build_deployment_batch_node_spec,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE


CORE_NODE_SPEC = build_deployment_batch_node_spec(
    node_type_id="core.model.detection-batch",
    display_name="Detection Batch",
    task_type=DETECTION_TASK_TYPE,
    output_name="detections_batch",
    output_display_name="Detections Batch",
    output_payload_type_id="detections-batch.v1",
    format_id="amvision.detections-batch.v1",
)
