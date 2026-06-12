"""缺陷聚类数量统计节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._reference_diff_node_support import (
    compute_reference_diff_metrics,
    require_regions_with_optional_roi,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _defect_cluster_count_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计差异/缺陷区域在当前作用域内形成了多少个有效缺陷聚类。"""

    regions_payload, roi_payload = require_regions_with_optional_roi(request)
    metrics_payload = compute_reference_diff_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    cluster_items = [
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
            "effective_area": item["effective_area"],
            "effective_area_ratio": item["effective_area_ratio"],
            "inside_scope_ratio": item["inside_scope_ratio"],
        }
        for item in metrics_payload["items"]
    ]
    return {
        "value": build_value_payload(
            {
                **metrics_payload,
                "cluster_count": metrics_payload["active_region_count"],
                "items": cluster_items,
            }
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.defect-cluster-count",
        display_name="Defect Cluster Count",
        category="vision.defect",
        description="统计 ROI 或整图内有效缺陷聚类数量，适合脏污、颗粒、点状缺陷和多点异常计数。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
            NodePortDefinition(
                name="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        capability_tags=("vision.defect", "inspection.defect.cluster", "inspection.defect.count"),
    ),
    handler=_defect_cluster_count_handler,
)
