"""region 圆度检查节点。"""

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
    compute_regions_circularity_metrics,
    read_optional_number,
    require_regions_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "circularity-check"


def _circularity_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据圆度和外接圆填充率判断区域是否足够接近圆形。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    match_mode = _read_match_mode(request.parameters.get("match_mode"))
    min_circularity = _read_optional_ratio(request.parameters.get("min_circularity"), field_name="min_circularity")
    max_circularity = _read_optional_ratio(request.parameters.get("max_circularity"), field_name="max_circularity")
    min_fill_ratio = _read_optional_ratio(request.parameters.get("min_fill_ratio"), field_name="min_fill_ratio")
    if min_circularity is None and max_circularity is None and min_fill_ratio is None:
        raise InvalidRequestError(f"{NODE_NAME} 节点至少需要设置一个圆度阈值参数")

    circularity_metrics = compute_regions_circularity_metrics(request, regions_payload=regions_payload)
    checked_items: list[dict[str, object]] = []
    passed_items: list[dict[str, object]] = []
    failed_items: list[dict[str, object]] = []
    for item in circularity_metrics["items"]:
        failure_reasons: list[str] = []
        circularity = item["circularity"]
        fill_ratio = item["min_enclosing_circle_fill_ratio"]
        perimeter_pixels = item["perimeter_pixels"]
        if not isinstance(perimeter_pixels, (int, float)) or float(perimeter_pixels) <= 0:
            failure_reasons.append("invalid-perimeter")
        if min_circularity is not None:
            if not isinstance(circularity, (int, float)):
                failure_reasons.append("missing-circularity")
            elif float(circularity) < min_circularity:
                failure_reasons.append("low-circularity")
        if max_circularity is not None:
            if not isinstance(circularity, (int, float)):
                failure_reasons.append("missing-circularity")
            elif float(circularity) > max_circularity:
                failure_reasons.append("high-circularity")
        if min_fill_ratio is not None:
            if not isinstance(fill_ratio, (int, float)):
                failure_reasons.append("missing-fill-ratio")
            elif float(fill_ratio) < min_fill_ratio:
                failure_reasons.append("low-fill-ratio")
        is_circular = len(failure_reasons) == 0
        checked_item = {
            **item,
            "circular": is_circular,
            "failure_reasons": failure_reasons,
        }
        checked_items.append(checked_item)
        if is_circular:
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
                "count": circularity_metrics["count"],
                "image_width": circularity_metrics["image_width"],
                "image_height": circularity_metrics["image_height"],
                "match_mode": match_mode,
                "min_circularity": min_circularity,
                "max_circularity": max_circularity,
                "min_fill_ratio": min_fill_ratio,
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
    """读取聚合模式。"""

    if raw_value is None:
        return "all"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 match_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"all", "any"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 match_mode 仅支持 all 或 any")
    return normalized_value


def _read_optional_ratio(raw_value: object, *, field_name: str) -> float | None:
    """读取可选 0 到 1 比例阈值。"""

    normalized_value = read_optional_number(raw_value, field_name=field_name, node_name=NODE_NAME)
    if normalized_value is None:
        return None
    if normalized_value < 0.0 or normalized_value > 1.0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须在 0 到 1 之间")
    return float(normalized_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.circularity-check",
        display_name="Circularity Check",
        category="vision.region",
        description="基于 regions.v1 的圆度和外接圆填充率判断区域是否足够接近圆形，适合孔、垫片、圆帽和圆孔缺陷检查。",
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
                "min_circularity": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最小圆度",
                },
                "max_circularity": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最大圆度",
                },
                "min_fill_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最小外接圆填充率",
                },
            },
        },
        capability_tags=("vision.region", "inspection.circularity", "inspection.roundness"),
    ),
    handler=_circularity_check_handler,
)
