"""Poses Batch 到 value List 的桥接节点。"""

from backend.nodes.core_nodes.support.model_batch_bridges import (
    build_model_batch_to_value_list_node_spec,
)
from backend.nodes.core_nodes.support.typed_payload_bridges import (
    require_poses_payload,
)
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE


CORE_NODE_SPEC = build_model_batch_to_value_list_node_spec(
    node_type_id="core.logic.poses-batch-to-value-list",
    display_name="Poses Batch To Value List",
    input_name="poses_batch",
    input_display_name="Poses Batch",
    input_payload_type_id="poses-batch.v1",
    format_id="amvision.poses-batch.v1",
    task_type=POSE_TASK_TYPE,
    result_payload_type_id="poses.v1",
    result_validator=require_poses_payload,
)
