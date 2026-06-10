"""缺陷密度统计节点。"""

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


def _defect_density_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计当前作用域内的缺陷密度指标。"""

    regions_payload, roi_payload = require_regions_with_optional_roi(request)
    metrics_payload = compute_reference_diff_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    scope_area = int(metrics_payload["scope_area"])
    active_region_count = int(metrics_payload["active_region_count"])
    cluster_count_per_10k_pixels = float(active_region_count / scope_area * 10000.0) if scope_area > 0 else 0.0
    return {
        "value": build_value_payload(
            {
                **metrics_payload,
                "cluster_count_per_10k_pixels": cluster_count_per_10k_pixels,
                "sum_effective_area_ratio": float(metrics_payload["sum_effective_area"] / scope_area) if scope_area > 0 else 0.0,
            }
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.defect-density",
        display_name="Defect Density",
        category="vision.defect",
        description="统计缺陷区域数量密度与面积密度，适合脏污、颗粒、点蚀和表面分布均匀性分析。",
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
        capability_tags=("vision.defect", "inspection.defect.density", "inspection.surface"),
    ),
    handler=_defect_density_handler,
)
