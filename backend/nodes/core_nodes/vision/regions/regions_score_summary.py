"""regions score 摘要节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import build_score_summary, require_regions_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _regions_score_summary_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计 regions.v1 的 score 摘要。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    return {"value": build_value_payload(build_score_summary(regions_payload["items"]))}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-score-summary",
        display_name="Region Score Summary",
        category="vision.region",
        description="统计 regions.v1 的 score 最小值、最大值、平均值和中位数，适合做置信度质量检查。",
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
        capability_tags=("vision.region", "vision.region.score", "inspection.quality"),
    ),
    handler=_regions_score_summary_handler,
)
