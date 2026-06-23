"""表面均匀性指标节点。"""

from __future__ import annotations

from statistics import pstdev

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.reference_diff import (
    compute_reference_diff_metrics,
    require_regions_with_optional_roi,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _surface_uniformity_metrics_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """汇总更贴表面异常场景的覆盖率、密度和聚集度指标。"""

    regions_payload, roi_payload = require_regions_with_optional_roi(request)
    metrics_payload = compute_reference_diff_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    effective_areas = [int(item["effective_area"]) for item in metrics_payload["items"]]
    scope_area = int(metrics_payload["scope_area"])
    total_diff_area = int(metrics_payload["total_diff_area"])
    sum_effective_area = int(metrics_payload["sum_effective_area"])
    largest_diff_area = int(metrics_payload["largest_diff_area"])
    avg_diff_area = float(metrics_payload["avg_diff_area"])
    cluster_count_per_10k_pixels = (
        float(metrics_payload["active_region_count"] / scope_area * 10000.0) if scope_area > 0 else 0.0
    )
    cluster_area_stddev = float(pstdev(effective_areas)) if effective_areas else 0.0
    return {
        "value": build_value_payload(
            {
                **metrics_payload,
                "coverage_ratio": float(metrics_payload["total_diff_area_ratio"]),
                "sum_effective_area_ratio": float(sum_effective_area / scope_area) if scope_area > 0 else 0.0,
                "cluster_count_per_10k_pixels": cluster_count_per_10k_pixels,
                "largest_cluster_share_of_diff": float(largest_diff_area / total_diff_area)
                if total_diff_area > 0
                else 0.0,
                "overlap_ratio": float(metrics_payload["union_overlap_area"] / sum_effective_area)
                if sum_effective_area > 0
                else 0.0,
                "cluster_area_stddev": cluster_area_stddev,
                "cluster_area_stddev_ratio": float(cluster_area_stddev / scope_area) if scope_area > 0 else 0.0,
                "cluster_area_cv": float(cluster_area_stddev / avg_diff_area) if avg_diff_area > 0 else 0.0,
            }
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.surface-uniformity-metrics",
        display_name="Surface Uniformity Metrics",
        category="vision.defect",
        description="把表面异常区域汇总成覆盖率、密度和聚集度指标，适合脏污、油污、涂层不均和点状缺陷分析。",
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
        capability_tags=("vision.defect", "inspection.surface", "inspection.surface.uniformity"),
    ),
    handler=_surface_uniformity_metrics_handler,
)
