"""region 跨度与主方向量测节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._region_node_support import compute_regions_span_metrics, require_regions_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _region_span_metrics_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """提取 region 的跨度、主方向和细长度量测指标。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    span_metrics = compute_regions_span_metrics(request, regions_payload=regions_payload)
    long_spans = [float(item["long_span_pixels"]) for item in span_metrics["items"]]
    short_spans = [float(item["short_span_pixels"]) for item in span_metrics["items"]]
    elongation_ratios = [
        float(item["elongation_ratio"])
        for item in span_metrics["items"]
        if item["elongation_ratio"] is not None
    ]
    return {
        "value": build_value_payload(
            {
                **span_metrics,
                "max_long_span_pixels": max(long_spans) if long_spans else None,
                "max_short_span_pixels": max(short_spans) if short_spans else None,
                "avg_long_span_pixels": (sum(long_spans) / len(long_spans)) if long_spans else None,
                "avg_short_span_pixels": (sum(short_spans) / len(short_spans)) if short_spans else None,
                "max_elongation_ratio": max(elongation_ratios) if elongation_ratios else None,
                "avg_elongation_ratio": (sum(elongation_ratios) / len(elongation_ratios)) if elongation_ratios else None,
            }
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.region-span-metrics",
        display_name="Region Span Metrics",
        category="vision.region",
        description="提取区域的长轴跨度、短轴跨度、方向角和细长度，适合焊缝、胶线、密封条和裂纹类目标的量测判断。",
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
        capability_tags=("vision.region", "inspection.measurement", "inspection.span"),
    ),
    handler=_region_span_metrics_handler,
)
