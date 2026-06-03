"""regions 覆盖率检查节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._roi_node_support import (
    compute_regions_intersection_metrics,
    read_optional_number,
    require_regions_payload,
    require_roi_payload,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "regions-coverage-check"


def _regions_coverage_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 ROI 覆盖率阈值判断是否达标。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    roi_payload = require_roi_payload(request.input_values.get("roi"), node_id=request.node_id)
    min_ratio = read_optional_number(request.parameters.get("min_ratio"), field_name="min_ratio", node_name=NODE_NAME)
    max_ratio = read_optional_number(request.parameters.get("max_ratio"), field_name="max_ratio", node_name=NODE_NAME)
    metrics_payload = compute_regions_intersection_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    roi_coverage_ratio = float(metrics_payload["roi_coverage_ratio"])
    is_ok = True
    if min_ratio is not None and roi_coverage_ratio < min_ratio:
        is_ok = False
    if max_ratio is not None and roi_coverage_ratio > max_ratio:
        is_ok = False
    return {
        "result": build_boolean_payload(is_ok),
        "metrics": build_value_payload(
            {
                **metrics_payload,
                "checked_metric": "roi_coverage_ratio",
                "min_ratio": min_ratio,
                "max_ratio": max_ratio,
                "result": is_ok,
            }
        ),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-coverage-check",
        display_name="Regions Coverage Check",
        category="vision.roi",
        description="根据 regions 对 ROI 的覆盖率判断是否达标，适合点胶、涂层和区域覆盖判定。",
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
                name="result",
                display_name="Result",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "min_ratio": {"type": "number", "title": "最小覆盖率"},
                "max_ratio": {"type": "number", "title": "最大覆盖率"},
            },
        },
        capability_tags=("vision.roi", "inspection.coverage", "inspection.coverage.check"),
    ),
    handler=_regions_coverage_check_handler,
)
