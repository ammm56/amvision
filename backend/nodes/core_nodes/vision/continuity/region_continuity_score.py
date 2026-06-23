"""region 连续性分数节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import compute_regions_integrity_metrics, require_regions_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _region_continuity_score_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """基于完整性原子指标计算连续性分数。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    integrity_metrics = compute_regions_integrity_metrics(request, regions_payload=regions_payload)
    score_items: list[dict[str, object]] = []
    continuity_scores: list[float] = []
    for item in integrity_metrics["items"]:
        component_score = float(1.0 / max(1, int(item["component_count"])))
        largest_component_score = float(item["largest_component_ratio"])
        hole_score = float(1.0 / (1 + int(item["hole_count"])))
        continuity_score = float(component_score * largest_component_score * hole_score)
        continuity_scores.append(continuity_score)
        score_items.append(
            {
                "region_id": item["region_id"],
                "class_id": item["class_id"],
                "class_name": item["class_name"],
                "prompt_id": item["prompt_id"],
                "track_id": item["track_id"],
                "state": item["state"],
                "score": item["score"],
                "mask_area": item["mask_area"],
                "component_count": item["component_count"],
                "largest_component_ratio": item["largest_component_ratio"],
                "hole_count": item["hole_count"],
                "component_score": component_score,
                "largest_component_score": largest_component_score,
                "hole_score": hole_score,
                "continuity_score": continuity_score,
            }
        )
    return {
        "value": build_value_payload(
            {
                "count": integrity_metrics["count"],
                "image_width": integrity_metrics["image_width"],
                "image_height": integrity_metrics["image_height"],
                "score_formula": "largest_component_ratio * (1/component_count) * (1/(1+hole_count))",
                "items": score_items,
                "min_score": min(continuity_scores) if continuity_scores else None,
                "max_score": max(continuity_scores) if continuity_scores else None,
                "avg_score": (sum(continuity_scores) / len(continuity_scores)) if continuity_scores else None,
            }
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.region-continuity-score",
        display_name="Region Continuity Score",
        category="vision.region",
        description="基于连通域数量、最大连通域占比和空洞数量生成 0 到 1 的连续性分数，适合做焊缝、胶线和密封条连续性分级。",
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
        capability_tags=("vision.region", "inspection.continuity", "inspection.continuity.score"),
    ),
    handler=_region_continuity_score_handler,
)
