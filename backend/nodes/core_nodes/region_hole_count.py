"""region 空洞数量统计节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._region_node_support import compute_regions_integrity_metrics, require_regions_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _region_hole_count_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计 regions.v1 中每个区域的空洞数量。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    integrity_metrics = compute_regions_integrity_metrics(request, regions_payload=regions_payload)
    hole_items = [
        {
            "region_id": item["region_id"],
            "class_id": item["class_id"],
            "class_name": item["class_name"],
            "prompt_id": item["prompt_id"],
            "track_id": item["track_id"],
            "state": item["state"],
            "score": item["score"],
            "declared_area": item["declared_area"],
            "mask_area": item["mask_area"],
            "component_count": item["component_count"],
            "hole_count": item["hole_count"],
        }
        for item in integrity_metrics["items"]
    ]
    hole_counts = [int(item["hole_count"]) for item in hole_items]
    return {
        "value": build_value_payload(
            {
                "count": integrity_metrics["count"],
                "image_width": integrity_metrics["image_width"],
                "image_height": integrity_metrics["image_height"],
                "items": hole_items,
                "total_hole_count": sum(hole_counts),
                "regions_with_holes": sum(1 for item in hole_items if int(item["hole_count"]) > 0),
                "max_hole_count": max(hole_counts) if hole_counts else 0,
                "avg_hole_count": (sum(hole_counts) / len(hole_counts)) if hole_counts else None,
            }
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.region-hole-count",
        display_name="Region Hole Count",
        category="vision.region",
        description="统计每个区域中的空洞数量，适合做涂层空洞、填充缺口和密封不连续检查。",
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
        capability_tags=("vision.region", "vision.region.hole", "inspection.integrity"),
    ),
    handler=_region_hole_count_handler,
)
