"""最大缺陷聚类占比节点。"""

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


def _defect_largest_cluster_ratio_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计最大缺陷聚类占总缺陷面积的比例。"""

    regions_payload, roi_payload = require_regions_with_optional_roi(request)
    metrics_payload = compute_reference_diff_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    largest_cluster_item = (
        max(metrics_payload["items"], key=lambda item: (int(item["effective_area"]), float(item["score"])))
        if metrics_payload["items"]
        else None
    )
    total_diff_area = int(metrics_payload["total_diff_area"])
    largest_cluster_ratio = (
        float(metrics_payload["largest_diff_area"] / total_diff_area)
        if total_diff_area > 0
        else 0.0
    )
    return {
        "value": build_value_payload(
            {
                **metrics_payload,
                "largest_cluster_ratio": largest_cluster_ratio,
                "largest_cluster_region_id": largest_cluster_item["region_id"] if largest_cluster_item is not None else None,
                "largest_cluster_class_name": largest_cluster_item["class_name"] if largest_cluster_item is not None else None,
            }
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.defect-largest-cluster-ratio",
        display_name="Defect Largest Cluster Ratio",
        category="vision.defect",
        description="统计最大缺陷聚类占总缺陷面积的比例，适合区分零散点状异常和单块大面积异常。",
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
        capability_tags=("vision.defect", "inspection.defect.cluster", "inspection.defect.ratio"),
    ),
    handler=_defect_largest_cluster_ratio_handler,
)
