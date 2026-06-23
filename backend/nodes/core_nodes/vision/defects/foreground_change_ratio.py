"""前景变化占比节点。"""

from __future__ import annotations

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


def _foreground_change_ratio_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把差异前景区域汇总为当前作用域内的变化占比。"""

    regions_payload, roi_payload = require_regions_with_optional_roi(request)
    metrics_payload = compute_reference_diff_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    return {"value": build_value_payload(float(metrics_payload["total_diff_area_ratio"]))}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.foreground-change-ratio",
        display_name="Foreground Change Ratio",
        category="vision.defect",
        description="把参考图差异、前景变化或 connected-components 结果汇总为当前 image 或 ROI 作用域内的总前景变化占比，适合直接接 threshold-check / range-check 做单帧工艺判定。",
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
        capability_tags=("vision.defect", "inspection.foreground", "inspection.foreground.change.ratio"),
    ),
    handler=_foreground_change_ratio_handler,
)
