"""Segments Batch 到完整关联项 List 的转换节点。"""

from backend.nodes.core_nodes.support.model_batch_items import (
    build_model_batch_to_items_node_spec,
)
from backend.nodes.core_nodes.vision.regions.segments_to_regions import (
    _require_segments_payload,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE


def _require_segments(payload: object, node_id: str) -> dict[str, object]:
    """适配现有 segments.v1 validator 的参数形式。"""

    return _require_segments_payload(payload, node_id=node_id)


CORE_NODE_SPEC = build_model_batch_to_items_node_spec(
    node_type_id="core.logic.segments-batch-to-items",
    display_name="Segments Batch To Items",
    input_name="segments_batch",
    input_display_name="Segments Batch",
    input_payload_type_id="segments-batch.v1",
    format_id="amvision.segments-batch.v1",
    task_type=SEGMENTATION_TASK_TYPE,
    result_payload_type_id="segments.v1",
    result_validator=_require_segments,
)
