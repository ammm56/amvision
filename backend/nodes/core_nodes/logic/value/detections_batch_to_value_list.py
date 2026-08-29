"""Detections Batch 到 value List 的桥接节点。"""

from backend.nodes.core_nodes.support.model_batch_bridges import (
    build_model_batch_to_value_list_node_spec,
)
from backend.nodes.core_nodes.support.typed_payload_bridges import (
    require_detections_payload,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE


CORE_NODE_SPEC = build_model_batch_to_value_list_node_spec(
    node_type_id="core.logic.detections-batch-to-value-list",
    display_name="Detections Batch To Value List",
    input_name="detections_batch",
    input_display_name="Detections Batch",
    input_payload_type_id="detections-batch.v1",
    format_id="amvision.detections-batch.v1",
    task_type=DETECTION_TASK_TYPE,
    result_payload_type_id="detections.v1",
    result_validator=require_detections_payload,
)
