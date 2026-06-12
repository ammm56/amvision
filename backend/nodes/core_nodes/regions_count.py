"""regions 数量统计节点。"""

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


def _regions_count_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计 regions.v1 中的区域数量。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    return {"value": build_value_payload(len(regions_payload["items"]))}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-count",
        display_name="Count Regions",
        category="vision.region",
        description="统计 regions.v1 中的区域数量，适合做目标存在性和数量达标判断。",
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
        capability_tags=("vision.region", "vision.region.count", "inspection.presence"),
    ),
    handler=_regions_count_handler,
)
