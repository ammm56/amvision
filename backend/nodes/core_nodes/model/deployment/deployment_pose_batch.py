"""deployment pose Batch 节点。"""

from backend.nodes.core_nodes.support.deployment_batch import (
    build_deployment_batch_node_spec,
)
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE


CORE_NODE_SPEC = build_deployment_batch_node_spec(
    node_type_id="core.model.pose-batch",
    display_name="Pose Batch",
    task_type=POSE_TASK_TYPE,
    output_name="poses_batch",
    output_display_name="Poses Batch",
    output_payload_type_id="poses-batch.v1",
    format_id="amvision.poses-batch.v1",
)
