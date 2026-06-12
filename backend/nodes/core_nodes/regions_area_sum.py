"""regions 面积汇总节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._region_node_support import require_regions_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _regions_area_sum_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计 regions.v1 的总面积。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    total_area = sum(int(item["area"]) for item in regions_payload["items"])
    return {"value": build_value_payload(total_area)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-area-sum",
        display_name="Sum Region Area",
        category="vision.region",
        description="统计 regions.v1 的总面积，适合做缺陷面积、覆盖面积和工艺区域面积汇总。",
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
        capability_tags=("vision.region", "vision.region.area", "inspection.area.sum"),
    ),
    handler=_regions_area_sum_handler,
)
