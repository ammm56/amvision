"""region 明显断裂/缺口检查节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes.support.region import (
    compute_regions_integrity_metrics,
    read_optional_int,
    read_optional_number,
    require_regions_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "region-gap-check"


def _region_gap_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据连通域数量、主体占比和空洞数判断是否存在明显断裂或缺口。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    match_mode = _read_match_mode(request.parameters.get("match_mode"))
    max_component_count = _read_max_component_count(request.parameters.get("max_component_count"))
    max_hole_count = _read_max_hole_count(request.parameters.get("max_hole_count"))
    min_largest_component_ratio = read_optional_number(
        request.parameters.get("min_largest_component_ratio"),
        field_name="min_largest_component_ratio",
        node_name=NODE_NAME,
    )
    integrity_metrics = compute_regions_integrity_metrics(request, regions_payload=regions_payload)
    checked_items: list[dict[str, object]] = []
    passed_items: list[dict[str, object]] = []
    failed_items: list[dict[str, object]] = []
    for item in integrity_metrics["items"]:
        failure_reasons: list[str] = []
        if int(item["component_count"]) > max_component_count:
            failure_reasons.append("too-many-components")
        if int(item["hole_count"]) > max_hole_count:
            failure_reasons.append("too-many-holes")
        if (
            min_largest_component_ratio is not None
            and float(item["largest_component_ratio"]) < min_largest_component_ratio
        ):
            failure_reasons.append("low-largest-component-ratio")
        is_gap_free = len(failure_reasons) == 0
        checked_item = {
            "region_id": item["region_id"],
            "class_id": item["class_id"],
            "class_name": item["class_name"],
            "prompt_id": item["prompt_id"],
            "track_id": item["track_id"],
            "state": item["state"],
            "score": item["score"],
            "mask_area": item["mask_area"],
            "component_count": item["component_count"],
            "component_areas": item["component_areas"],
            "largest_component_area": item["largest_component_area"],
            "largest_component_ratio": item["largest_component_ratio"],
            "hole_count": item["hole_count"],
            "hole_areas": item["hole_areas"],
            "gap_free": is_gap_free,
            "failure_reasons": failure_reasons,
        }
        checked_items.append(checked_item)
        if is_gap_free:
            passed_items.append(checked_item)
        else:
            failed_items.append(checked_item)
    if match_mode == "all":
        is_ok = bool(checked_items) and len(failed_items) == 0
    else:
        is_ok = len(passed_items) > 0
    return {
        "result": build_boolean_payload(is_ok),
        "metrics": build_value_payload(
            {
                "count": integrity_metrics["count"],
                "image_width": integrity_metrics["image_width"],
                "image_height": integrity_metrics["image_height"],
                "match_mode": match_mode,
                "max_component_count": max_component_count,
                "max_hole_count": max_hole_count,
                "min_largest_component_ratio": min_largest_component_ratio,
                "passed_count": len(passed_items),
                "failed_count": len(failed_items),
                "passed_region_ids": [item["region_id"] for item in passed_items],
                "failed_region_ids": [item["region_id"] for item in failed_items],
                "items": checked_items,
                "result": is_ok,
            }
        ),
    }


def _read_match_mode(raw_value: object) -> str:
    """读取 gap-check 聚合模式。"""

    if raw_value is None:
        return "all"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 match_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"all", "any"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 match_mode 仅支持 all 或 any")
    return normalized_value


def _read_max_component_count(raw_value: object) -> int:
    """读取最大允许连通域数量。"""

    normalized_value = read_optional_int(raw_value, field_name="max_component_count", node_name=NODE_NAME)
    if normalized_value is None:
        return 1
    if normalized_value < 1:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_component_count 必须大于等于 1")
    return normalized_value


def _read_max_hole_count(raw_value: object) -> int:
    """读取最大允许空洞数量。"""

    normalized_value = read_optional_int(raw_value, field_name="max_hole_count", node_name=NODE_NAME)
    if normalized_value is None:
        return 0
    if normalized_value < 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_hole_count 必须大于等于 0")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.region-gap-check",
        display_name="Region Gap Check",
        category="vision.region",
        description="根据连通域数量、主体占比和空洞数判断区域是否存在明显断裂或缺口，适合焊缝、胶线和密封条连续性检查。",
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
                    "enum": ["all", "any"],
                    "default": "all",
                    "title": "聚合模式",
                },
                "max_component_count": {
                    "type": "integer",
                    "default": 1,
                    "minimum": 1,
                    "title": "最大连通域数量",
                },
                "max_hole_count": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "title": "最大空洞数量",
                },
                "min_largest_component_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最小最大连通域占比",
                },
            },
        },
        capability_tags=("vision.region", "inspection.continuity", "inspection.gap.check"),
    ),
    handler=_region_gap_check_handler,
)
