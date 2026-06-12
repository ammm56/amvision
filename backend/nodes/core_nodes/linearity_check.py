"""region 线性度检查节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._region_node_support import (
    compute_regions_linearity_metrics,
    read_optional_number,
    require_regions_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "linearity-check"


def _linearity_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据拟合直线偏差判断区域是否足够直。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    match_mode = _read_match_mode(request.parameters.get("match_mode"))
    min_line_length_pixels = read_optional_number(
        request.parameters.get("min_line_length_pixels"),
        field_name="min_line_length_pixels",
        node_name=NODE_NAME,
    )
    max_rms_distance_pixels = read_optional_number(
        request.parameters.get("max_rms_distance_pixels"),
        field_name="max_rms_distance_pixels",
        node_name=NODE_NAME,
    )
    max_max_distance_pixels = read_optional_number(
        request.parameters.get("max_max_distance_pixels"),
        field_name="max_max_distance_pixels",
        node_name=NODE_NAME,
    )
    max_rms_distance_ratio = _read_optional_ratio(request.parameters.get("max_rms_distance_ratio"), "max_rms_distance_ratio")
    max_max_distance_ratio = _read_optional_ratio(request.parameters.get("max_max_distance_ratio"), "max_max_distance_ratio")
    if all(
        value is None
        for value in (
            min_line_length_pixels,
            max_rms_distance_pixels,
            max_max_distance_pixels,
            max_rms_distance_ratio,
            max_max_distance_ratio,
        )
    ):
        raise InvalidRequestError(f"{NODE_NAME} 节点至少需要设置一个线性度阈值参数")

    linearity_metrics = compute_regions_linearity_metrics(request, regions_payload=regions_payload)
    checked_items: list[dict[str, object]] = []
    passed_items: list[dict[str, object]] = []
    failed_items: list[dict[str, object]] = []
    for item in linearity_metrics["items"]:
        failure_reasons: list[str] = []
        line_length_pixels = item["line_length_pixels"]
        if not isinstance(line_length_pixels, (int, float)) or float(line_length_pixels) <= 0:
            failure_reasons.append("invalid-line-length")
        if min_line_length_pixels is not None and isinstance(line_length_pixels, (int, float)) and float(line_length_pixels) < min_line_length_pixels:
            failure_reasons.append("line-too-short")
        rms_distance_pixels = item["rms_distance_pixels"]
        if (
            max_rms_distance_pixels is not None
            and isinstance(rms_distance_pixels, (int, float))
            and float(rms_distance_pixels) > max_rms_distance_pixels
        ):
            failure_reasons.append("rms-distance-too-large")
        max_distance_pixels = item["max_distance_pixels"]
        if (
            max_max_distance_pixels is not None
            and isinstance(max_distance_pixels, (int, float))
            and float(max_distance_pixels) > max_max_distance_pixels
        ):
            failure_reasons.append("peak-distance-too-large")
        rms_distance_ratio = item["rms_distance_ratio"]
        if (
            max_rms_distance_ratio is not None
            and isinstance(rms_distance_ratio, (int, float))
            and float(rms_distance_ratio) > max_rms_distance_ratio
        ):
            failure_reasons.append("rms-distance-ratio-too-large")
        max_distance_ratio = item["max_distance_ratio"]
        if (
            max_max_distance_ratio is not None
            and isinstance(max_distance_ratio, (int, float))
            and float(max_distance_ratio) > max_max_distance_ratio
        ):
            failure_reasons.append("peak-distance-ratio-too-large")
        is_linear = len(failure_reasons) == 0
        checked_item = {
            **item,
            "linear": is_linear,
            "failure_reasons": failure_reasons,
        }
        checked_items.append(checked_item)
        if is_linear:
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
                "count": linearity_metrics["count"],
                "image_width": linearity_metrics["image_width"],
                "image_height": linearity_metrics["image_height"],
                "match_mode": match_mode,
                "min_line_length_pixels": min_line_length_pixels,
                "max_rms_distance_pixels": max_rms_distance_pixels,
                "max_max_distance_pixels": max_max_distance_pixels,
                "max_rms_distance_ratio": max_rms_distance_ratio,
                "max_max_distance_ratio": max_max_distance_ratio,
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


def _read_optional_ratio(raw_value: object, field_name: str) -> float | None:
    """读取可选 0 到 1 比例阈值。"""

    normalized_value = read_optional_number(raw_value, field_name=field_name, node_name=NODE_NAME)
    if normalized_value is None:
        return None
    if normalized_value < 0.0 or normalized_value > 1.0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须在 0 到 1 之间")
    return float(normalized_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.linearity-check",
        display_name="Linearity Check",
        category="vision.region",
        description="基于 regions.v1 的拟合直线偏差指标判断区域是否足够直，适合边缘直线度、条带直线度和细长工件姿态检查。",
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
                "min_line_length_pixels": {
                    "type": "number",
                    "minimum": 0,
                    "title": "最小线长",
                },
                "max_rms_distance_pixels": {
                    "type": "number",
                    "minimum": 0,
                    "title": "最大 RMS 偏差像素",
                },
                "max_max_distance_pixels": {
                    "type": "number",
                    "minimum": 0,
                    "title": "最大峰值偏差像素",
                },
                "max_rms_distance_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最大 RMS 偏差占比",
                },
                "max_max_distance_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最大峰值偏差占比",
                },
            },
        },
        capability_tags=("vision.region", "inspection.linearity", "inspection.straightness"),
    ),
    handler=_linearity_check_handler,
)
