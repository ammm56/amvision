"""region 最大连通域占比节点。"""

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


def _region_largest_component_ratio_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计 regions.v1 中每个区域的最大连通域占比。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    integrity_metrics = compute_regions_integrity_metrics(request, regions_payload=regions_payload)
    ratio_items = [
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
            "largest_component_area": item["largest_component_area"],
            "largest_component_ratio": item["largest_component_ratio"],
        }
        for item in integrity_metrics["items"]
    ]
    ratios = [float(item["largest_component_ratio"]) for item in ratio_items]
    return {
        "value": build_value_payload(
            {
                "count": integrity_metrics["count"],
                "image_width": integrity_metrics["image_width"],
                "image_height": integrity_metrics["image_height"],
                "items": ratio_items,
                "min_ratio": min(ratios) if ratios else None,
                "max_ratio": max(ratios) if ratios else None,
                "avg_ratio": (sum(ratios) / len(ratios)) if ratios else None,
            }
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.region-largest-component-ratio",
        display_name="Region Largest Component Ratio",
        category="vision.region",
        description="统计每个区域最大连通域占整体前景面积的比例，适合做主体完整性和碎裂占比判断。",
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
        capability_tags=("vision.region", "vision.region.component", "inspection.integrity"),
    ),
    handler=_region_largest_component_ratio_handler,
)
