"""regions 落位检查节点。"""

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
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "regions-inside-check"


def _regions_inside_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """判断区域是否位于指定 ROI 内部。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    roi_payload = require_roi_payload(request.input_values.get("roi"), node_id=request.node_id)
    match_mode = _read_match_mode(request.parameters.get("match_mode"))
    min_inside_ratio = read_optional_number(
        request.parameters.get("min_inside_ratio"),
        field_name="min_inside_ratio",
        node_name=NODE_NAME,
    )
    effective_min_inside_ratio = 1.0 if min_inside_ratio is None else min_inside_ratio
    metrics_payload = compute_regions_intersection_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    metrics_items = list(metrics_payload["items"])
    matched_items = [
        dict(item)
        for item in metrics_items
        if float(item["inside_ratio"]) >= effective_min_inside_ratio
    ]
    if match_mode == "all":
        is_ok = bool(metrics_items) and len(matched_items) == len(metrics_items)
    else:
        is_ok = len(matched_items) > 0
    return {
        "result": build_boolean_payload(is_ok),
        "metrics": build_value_payload(
            {
                **metrics_payload,
                "match_mode": match_mode,
                "min_inside_ratio": effective_min_inside_ratio,
                "matched_count": len(matched_items),
                "matched_region_ids": [item["region_id"] for item in matched_items],
                "result": is_ok,
            }
        ),
    }


def _read_match_mode(raw_value: object) -> str:
    """读取落位检查匹配模式。"""

    if raw_value is None:
        return "any"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("regions-inside-check 节点的 match_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"any", "all"}:
        raise InvalidRequestError("regions-inside-check 仅支持 any 或 all")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-inside-check",
        display_name="Regions Inside Check",
        category="vision.roi",
        description="判断 regions 是否位于指定 ROI 内部，适合工位落位和越界规则判断。",
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
                "match_mode": {
                    "type": "string",
                    "enum": ["any", "all"],
                    "default": "any",
                    "title": "匹配模式",
                },
                "min_inside_ratio": {"type": "number", "title": "最小内部占比", "default": 1.0},
            },
        },
        capability_tags=("vision.roi", "inspection.position", "inspection.inside"),
    ),
    handler=_regions_inside_check_handler,
)
