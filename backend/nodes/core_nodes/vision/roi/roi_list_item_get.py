"""ROI 列表项读取节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.nodes.core_nodes.support.roi import require_roi_list_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "roi-list-item-get"


def _roi_list_item_get_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按索引从 roi-list.v1 中读取单个 roi.v1。"""

    roi_list_payload = require_roi_list_payload(request.input_values.get("rois"), node_id=request.node_id)
    roi_items = roi_list_payload["items"]
    resolved_index = _resolve_index(request)
    allow_negative = _read_bool(request.parameters.get("allow_negative"), default=True)
    normalized_index = resolved_index
    if normalized_index < 0 and allow_negative:
        normalized_index += len(roi_items)
    if not 0 <= normalized_index < len(roi_items):
        raise InvalidRequestError(
            f"{NODE_NAME} 节点索引越界",
            details={
                "node_id": request.node_id,
                "index": resolved_index,
                "normalized_index": normalized_index,
                "size": len(roi_items),
            },
        )
    roi_payload = roi_items[normalized_index]
    return {
        "roi": roi_payload,
        "summary": build_value_payload(
            {
                "index": resolved_index,
                "normalized_index": normalized_index,
                "roi_id": roi_payload.get("roi_id"),
                "roi_kind": roi_payload.get("roi_kind"),
                "area": roi_payload.get("area"),
            }
        ),
    }


def _resolve_index(request: WorkflowNodeExecutionRequest) -> int:
    """从 index 输入端口或节点参数读取目标索引。"""

    index_payload = request.input_values.get("index")
    if index_payload is not None:
        raw_index = require_value_payload(index_payload, field_name="index")["value"]
    else:
        raw_index = request.parameters.get("index", 0)
    if isinstance(raw_index, bool) or not isinstance(raw_index, int):
        raise InvalidRequestError(
            f"{NODE_NAME} 节点要求 index 必须是整数",
            details={"node_id": request.node_id, "index": raw_index},
        )
    return raw_index


def _read_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError(
        f"{NODE_NAME} 节点要求 allow_negative 必须是布尔值",
        details={"allow_negative": raw_value},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.roi-list-item-get",
        display_name="ROI List Item Get",
        category="vision.roi",
        description="按索引从 roi-list.v1 中读取单个 roi.v1，供 Crop、Draw ROI 和单 ROI 规则节点使用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="rois",
                display_name="ROIs",
                payload_type_id="roi-list.v1",
            ),
            NodePortDefinition(
                name="index",
                display_name="Index",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "title": "Index",
                    "default": 0,
                    "description": "要读取的 ROI 索引，支持负索引时 -1 表示最后一个。",
                },
                "allow_negative": {
                    "type": "boolean",
                    "title": "Allow negative",
                    "default": True,
                    "description": "是否允许负索引。",
                },
            },
            "required": [],
        },
        capability_tags=("vision.roi", "vision.roi.list", "list.read"),
    ),
    handler=_roi_list_item_get_handler,
)
