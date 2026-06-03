"""regions bbox 指标节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._region_node_support import compute_region_bbox_metrics, require_regions_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _regions_bbox_metrics_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """提取 regions.v1 的 bbox 派生指标。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    metrics_items = [compute_region_bbox_metrics(item) for item in regions_payload["items"]]
    widths = [float(item["width"]) for item in metrics_items]
    heights = [float(item["height"]) for item in metrics_items]
    aspect_ratios = [float(item["aspect_ratio"]) for item in metrics_items if item["aspect_ratio"] is not None]
    payload_value: dict[str, object] = {
        "count": len(metrics_items),
        "items": metrics_items,
        "max_width": max(widths) if widths else None,
        "max_height": max(heights) if heights else None,
        "avg_width": (sum(widths) / len(widths)) if widths else None,
        "avg_height": (sum(heights) / len(heights)) if heights else None,
        "avg_aspect_ratio": (sum(aspect_ratios) / len(aspect_ratios)) if aspect_ratios else None,
    }
    return {"value": build_value_payload(payload_value)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-bbox-metrics",
        display_name="Region BBox Metrics",
        category="vision.region",
        description="提取 regions.v1 的 bbox 宽、高、长宽比和中心点指标，适合做位置偏移和尺寸规则判断。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        capability_tags=("vision.region", "vision.region.bbox", "inspection.position"),
    ),
    handler=_regions_bbox_metrics_handler,
)
