"""region 边缘断裂检查节点。"""

from __future__ import annotations

import math

import numpy as np

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._region_node_support import (
    build_region_binary_mask,
    compute_regions_span_metrics,
    read_optional_int,
    read_optional_number,
    require_regions_payload,
    resolve_region_canvas_size,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "edge-break-check"


def _edge_break_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据区域主方向投影后的空段情况判断是否存在明显断边。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    match_mode = _read_match_mode(request.parameters.get("match_mode"))
    min_gap_pixels_to_count = _read_min_gap_pixels_to_count(request.parameters.get("min_gap_pixels_to_count"))
    max_gap_pixels = _read_max_gap_pixels(request.parameters.get("max_gap_pixels"))
    max_gap_count = _read_max_gap_count(request.parameters.get("max_gap_count"))
    min_elongation_ratio = read_optional_number(
        request.parameters.get("min_elongation_ratio"),
        field_name="min_elongation_ratio",
        node_name=NODE_NAME,
    )
    min_axis_occupancy_ratio = _read_optional_ratio(
        request.parameters.get("min_axis_occupancy_ratio"),
        field_name="min_axis_occupancy_ratio",
    )

    image_width, image_height = resolve_region_canvas_size(request, regions_payload=regions_payload)
    span_metrics = compute_regions_span_metrics(request, regions_payload=regions_payload)
    span_metrics_by_region_id = {str(item["region_id"]): item for item in span_metrics["items"]}

    checked_items: list[dict[str, object]] = []
    passed_items: list[dict[str, object]] = []
    failed_items: list[dict[str, object]] = []
    for region_item in regions_payload["items"]:
        region_id = str(region_item["region_id"])
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        edge_axis_metrics = _compute_edge_axis_gap_metrics(
            mask_matrix=region_mask,
            orientation_deg=span_metrics_by_region_id[region_id]["orientation_deg"],
            min_gap_pixels_to_count=min_gap_pixels_to_count,
        )
        current_span_metrics = span_metrics_by_region_id[region_id]
        failure_reasons: list[str] = []
        current_elongation_ratio = current_span_metrics["elongation_ratio"]
        if (
            min_elongation_ratio is not None
            and (
                current_elongation_ratio is None
                or float(current_elongation_ratio) < float(min_elongation_ratio)
            )
        ):
            failure_reasons.append("low-elongation-ratio")
        if int(edge_axis_metrics["gap_count"]) > max_gap_count:
            failure_reasons.append("too-many-axis-gaps")
        if float(edge_axis_metrics["longest_gap_pixels"]) > float(max_gap_pixels):
            failure_reasons.append("axis-gap-too-large")
        if (
            min_axis_occupancy_ratio is not None
            and float(edge_axis_metrics["axis_occupancy_ratio"]) < min_axis_occupancy_ratio
        ):
            failure_reasons.append("low-axis-occupancy-ratio")
        is_ok = len(failure_reasons) == 0
        checked_item = {
            "region_id": region_id,
            "class_id": current_span_metrics["class_id"],
            "class_name": current_span_metrics["class_name"],
            "prompt_id": current_span_metrics["prompt_id"],
            "track_id": current_span_metrics["track_id"],
            "state": current_span_metrics["state"],
            "score": current_span_metrics["score"],
            "mask_area": current_span_metrics["mask_area"],
            "x_span_pixels": current_span_metrics["x_span_pixels"],
            "y_span_pixels": current_span_metrics["y_span_pixels"],
            "long_span_pixels": current_span_metrics["long_span_pixels"],
            "short_span_pixels": current_span_metrics["short_span_pixels"],
            "elongation_ratio": current_elongation_ratio,
            "orientation_deg": current_span_metrics["orientation_deg"],
            "axis_aligned_fill_ratio": current_span_metrics["axis_aligned_fill_ratio"],
            **edge_axis_metrics,
            "edge_intact": is_ok,
            "failure_reasons": failure_reasons,
        }
        checked_items.append(checked_item)
        if is_ok:
            passed_items.append(checked_item)
        else:
            failed_items.append(checked_item)

    if match_mode == "all":
        result_value = bool(checked_items) and len(failed_items) == 0
    else:
        result_value = len(passed_items) > 0
    return {
        "result": build_boolean_payload(result_value),
        "metrics": build_value_payload(
            {
                "count": len(checked_items),
                "image_width": image_width,
                "image_height": image_height,
                "match_mode": match_mode,
                "min_gap_pixels_to_count": min_gap_pixels_to_count,
                "max_gap_pixels": max_gap_pixels,
                "max_gap_count": max_gap_count,
                "min_elongation_ratio": min_elongation_ratio,
                "min_axis_occupancy_ratio": min_axis_occupancy_ratio,
                "passed_count": len(passed_items),
                "failed_count": len(failed_items),
                "passed_region_ids": [item["region_id"] for item in passed_items],
                "failed_region_ids": [item["region_id"] for item in failed_items],
                "items": checked_items,
                "result": result_value,
            }
        ),
    }


def _compute_edge_axis_gap_metrics(
    *,
    mask_matrix: np.ndarray,
    orientation_deg: object,
    min_gap_pixels_to_count: int,
) -> dict[str, object]:
    """沿区域主方向统计空段分布。"""

    foreground_points_yx = np.column_stack(np.nonzero(mask_matrix > 0))
    if foreground_points_yx.size <= 0:
        return {
            "axis_bin_count": 0,
            "occupied_bin_count": 0,
            "axis_occupancy_ratio": 0.0,
            "gap_count": 0,
            "gap_lengths": [],
            "longest_gap_pixels": 0.0,
        }
    orientation_value = float(orientation_deg or 0.0)
    angle_radians = math.radians(orientation_value)
    direction_vector = np.array([math.cos(angle_radians), math.sin(angle_radians)], dtype=np.float32)
    point_cloud_xy = np.column_stack(
        (foreground_points_yx[:, 1].astype(np.float32), foreground_points_yx[:, 0].astype(np.float32))
    )
    projection_values = point_cloud_xy @ direction_vector
    min_projection = float(np.min(projection_values))
    shifted_projection_values = projection_values - min_projection
    bin_indices = np.floor(shifted_projection_values + 1e-6).astype(np.int32)
    if bin_indices.size <= 0:
        return {
            "axis_bin_count": 0,
            "occupied_bin_count": 0,
            "axis_occupancy_ratio": 0.0,
            "gap_count": 0,
            "gap_lengths": [],
            "longest_gap_pixels": 0.0,
        }
    axis_bin_count = int(np.max(bin_indices)) + 1
    occupancy_counts = np.bincount(bin_indices, minlength=axis_bin_count)
    occupied_mask = occupancy_counts > 0
    occupied_bin_count = int(np.count_nonzero(occupied_mask))
    gap_lengths: list[int] = []
    current_gap_length = 0
    seen_foreground = False
    last_occupied_index = int(np.max(np.nonzero(occupied_mask)[0])) if occupied_bin_count > 0 else -1
    for bin_index, occupied in enumerate(occupied_mask.tolist()):
        if not occupied:
            if seen_foreground and bin_index < last_occupied_index:
                current_gap_length += 1
            continue
        seen_foreground = True
        if current_gap_length >= min_gap_pixels_to_count:
            gap_lengths.append(current_gap_length)
        current_gap_length = 0
    longest_gap_pixels = float(max(gap_lengths)) if gap_lengths else 0.0
    axis_occupancy_ratio = float(occupied_bin_count / axis_bin_count) if axis_bin_count > 0 else 0.0
    return {
        "axis_bin_count": axis_bin_count,
        "occupied_bin_count": occupied_bin_count,
        "axis_occupancy_ratio": round(axis_occupancy_ratio, 6),
        "gap_count": len(gap_lengths),
        "gap_lengths": gap_lengths,
        "longest_gap_pixels": round(longest_gap_pixels, 4),
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


def _read_min_gap_pixels_to_count(raw_value: object) -> int:
    """读取计入断边的最小 gap 长度。"""

    normalized_value = read_optional_int(raw_value, field_name="min_gap_pixels_to_count", node_name=NODE_NAME)
    if normalized_value is None:
        return 2
    if normalized_value < 1:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 min_gap_pixels_to_count 必须大于等于 1")
    return normalized_value


def _read_max_gap_pixels(raw_value: object) -> int:
    """读取允许的最大 gap 长度。"""

    normalized_value = read_optional_int(raw_value, field_name="max_gap_pixels", node_name=NODE_NAME)
    if normalized_value is None:
        return 0
    if normalized_value < 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_gap_pixels 必须大于等于 0")
    return normalized_value


def _read_max_gap_count(raw_value: object) -> int:
    """读取允许的最大 gap 数量。"""

    normalized_value = read_optional_int(raw_value, field_name="max_gap_count", node_name=NODE_NAME)
    if normalized_value is None:
        return 0
    if normalized_value < 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_gap_count 必须大于等于 0")
    return normalized_value


def _read_optional_ratio(raw_value: object, *, field_name: str) -> float | None:
    """读取可选 0 到 1 比例参数。"""

    normalized_value = read_optional_number(raw_value, field_name=field_name, node_name=NODE_NAME)
    if normalized_value is None:
        return None
    if normalized_value < 0.0 or normalized_value > 1.0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须在 0 到 1 之间")
    return float(normalized_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.edge-break-check",
        display_name="Edge Break Check",
        category="vision.region",
        description="沿区域主方向投影后检查内部空段数量与长度，判断是否存在明显断边、崩边或裂纹式断段。",
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
                "min_gap_pixels_to_count": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 2,
                    "title": "计入断边的最小空段像素",
                },
                "max_gap_pixels": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "title": "最大允许空段像素",
                },
                "max_gap_count": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "title": "最大允许空段数量",
                },
                "min_elongation_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "title": "最小细长度",
                },
                "min_axis_occupancy_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最小主轴占用率",
                },
            },
        },
        capability_tags=("vision.region", "inspection.edge", "inspection.edge.break"),
    ),
    handler=_edge_break_check_handler,
)
