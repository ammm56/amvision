"""regions 与 ROI 交集指标节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import (
    compute_regions_intersection_metrics,
    require_regions_payload,
    require_roi_payload,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _regions_intersection_metrics_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算 regions 与 ROI 的交集、覆盖率和 IoU 指标。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    roi_payload = require_roi_payload(request.input_values.get("roi"), node_id=request.node_id)
    metrics_payload = compute_regions_intersection_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    return {"value": build_value_payload(metrics_payload)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-intersection-metrics",
        display_name="Regions Intersection Metrics",
        category="vision.roi",
        description="计算 regions.v1 与 roi.v1 的交集面积、覆盖率、inside ratio 和 IoU 指标。",
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
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        capability_tags=("vision.roi", "inspection.coverage", "inspection.intersection"),
    ),
    handler=_regions_intersection_metrics_handler,
)
