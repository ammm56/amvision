"""显式边缘方向缺口检查节点。"""

from __future__ import annotations

import numpy as np

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._reference_diff_node_support import require_regions_with_optional_roi
from backend.nodes.core_nodes._region_node_support import (
    build_region_binary_mask,
    resolve_region_canvas_size,
)
from backend.nodes.core_nodes._roi_node_support import build_roi_mask
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "edge-profile-gap-check"


def _edge_profile_gap_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """沿显式边缘方向检查投影缺口。"""

    regions_payload, roi_payload = require_regions_with_optional_roi(request)
    edge_orientation = _read_edge_orientation(request.parameters.get("edge_orientation"))
    min_gap_pixels_to_count = _read_min_gap_pixels_to_count(request.parameters.get("min_gap_pixels_to_count"))
    max_gap_pixels = _read_max_gap_pixels(request.parameters.get("max_gap_pixels"))
    max_gap_count = _read_max_gap_count(request.parameters.get("max_gap_count"))
    min_axis_occupancy_ratio = _read_optional_ratio(
        request.parameters.get("min_axis_occupancy_ratio"),
        field_name="min_axis_occupancy_ratio",
    )

    image_width, image_height = resolve_region_canvas_size(request, regions_payload=regions_payload)
    scope_mask = (
        build_roi_mask(roi_payload=roi_payload, image_width=image_width, image_height=image_height)
        if roi_payload is not None
        else np.ones((image_height, image_width), dtype=np.uint8)
    )
    union_mask = np.zeros((image_height, image_width), dtype=np.uint8)
    active_region_ids: list[str] = []
    for region_item in regions_payload["items"]:
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        effective_mask = np.logical_and(region_mask > 0, scope_mask > 0).astype(np.uint8)
        if int(np.count_nonzero(effective_mask)) <= 0:
            continue
        union_mask = np.maximum(union_mask, effective_mask)
        active_region_ids.append(str(region_item["region_id"]))

    profile_metrics = _compute_profile_gap_metrics(
        mask_matrix=union_mask,
        edge_orientation=edge_orientation,
        min_gap_pixels_to_count=min_gap_pixels_to_count,
    )
    failure_reasons: list[str] = []
    if profile_metrics["axis_bin_count"] <= 0:
        failure_reasons.append("no-occupied-profile")
    if int(profile_metrics["gap_count"]) > max_gap_count:
        failure_reasons.append("too-many-profile-gaps")
    if float(profile_metrics["longest_gap_pixels"]) > float(max_gap_pixels):
        failure_reasons.append("profile-gap-too-large")
    if (
        min_axis_occupancy_ratio is not None
        and float(profile_metrics["axis_occupancy_ratio"]) < min_axis_occupancy_ratio
    ):
        failure_reasons.append("low-axis-occupancy-ratio")
    is_ok = len(failure_reasons) == 0
    return {
        "result": build_boolean_payload(is_ok),
        "metrics": build_value_payload(
            {
                "scope_kind": "roi" if roi_payload is not None else "image",
                "scope_id": str(roi_payload["roi_id"]) if roi_payload is not None else None,
                "image_width": image_width,
                "image_height": image_height,
                "edge_orientation": edge_orientation,
                "min_gap_pixels_to_count": min_gap_pixels_to_count,
                "max_gap_pixels": max_gap_pixels,
                "max_gap_count": max_gap_count,
                "min_axis_occupancy_ratio": min_axis_occupancy_ratio,
                "active_region_count": len(active_region_ids),
                "active_region_ids": active_region_ids,
                **profile_metrics,
                "failure_reasons": failure_reasons,
                "result": is_ok,
            }
        ),
    }


def _compute_profile_gap_metrics(
    *,
    mask_matrix: np.ndarray,
    edge_orientation: str,
    min_gap_pixels_to_count: int,
) -> dict[str, object]:
    """按显式方向统计投影 profile 的空段。"""

    occupancy_mask = np.any(mask_matrix > 0, axis=0 if edge_orientation == "horizontal" else 1)
    occupied_indices = np.nonzero(occupancy_mask)[0]
    if occupied_indices.size <= 0:
        return {
            "axis_bin_count": 0,
            "occupied_bin_count": 0,
            "axis_occupancy_ratio": 0.0,
            "gap_count": 0,
            "gap_lengths": [],
            "longest_gap_pixels": 0.0,
            "profile_start_index": None,
            "profile_end_index": None,
        }
    start_index = int(np.min(occupied_indices))
    end_index = int(np.max(occupied_indices))
    active_occupancy = occupancy_mask[start_index : end_index + 1]
    axis_bin_count = int(active_occupancy.shape[0])
    occupied_bin_count = int(np.count_nonzero(active_occupancy))
    gap_lengths: list[int] = []
    current_gap_length = 0
    for occupied in active_occupancy.tolist():
        if occupied:
            if current_gap_length >= min_gap_pixels_to_count:
                gap_lengths.append(current_gap_length)
            current_gap_length = 0
            continue
        current_gap_length += 1
    longest_gap_pixels = float(max(gap_lengths)) if gap_lengths else 0.0
    return {
        "axis_bin_count": axis_bin_count,
        "occupied_bin_count": occupied_bin_count,
        "axis_occupancy_ratio": round(float(occupied_bin_count / axis_bin_count), 6) if axis_bin_count > 0 else 0.0,
        "gap_count": len(gap_lengths),
        "gap_lengths": gap_lengths,
        "longest_gap_pixels": round(longest_gap_pixels, 4),
        "profile_start_index": start_index,
        "profile_end_index": end_index,
    }


def _read_edge_orientation(raw_value: object) -> str:
    """读取边缘方向。"""

    if raw_value is None:
        return "horizontal"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 edge_orientation 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"horizontal", "vertical"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 edge_orientation 仅支持 horizontal 或 vertical")
    return normalized_value


def _read_min_gap_pixels_to_count(raw_value: object) -> int:
    """读取计入缺口的最小 gap 长度。"""

    if raw_value is None:
        return 2
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 min_gap_pixels_to_count 必须是整数")
    if raw_value < 1:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 min_gap_pixels_to_count 必须大于等于 1")
    return int(raw_value)


def _read_max_gap_pixels(raw_value: object) -> int:
    """读取允许的最大缺口长度。"""

    if raw_value is None:
        return 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_gap_pixels 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_gap_pixels 必须大于等于 0")
    return int(raw_value)


def _read_max_gap_count(raw_value: object) -> int:
    """读取允许的最大缺口数量。"""

    if raw_value is None:
        return 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_gap_count 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 max_gap_count 必须大于等于 0")
    return int(raw_value)


def _read_optional_ratio(raw_value: object, *, field_name: str) -> float | None:
    """读取可选比例。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是数值")
    normalized_value = float(raw_value)
    if normalized_value < 0.0 or normalized_value > 1.0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须在 0 到 1 之间")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.edge-profile-gap-check",
        display_name="Edge Profile Gap Check",
        category="vision.defect",
        description="沿显式 horizontal/vertical 边缘方向做投影缺口检查，适合已知工位方向的边线、胶线或焊缝缺口判定。",
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
                required=False,
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
                "edge_orientation": {
                    "type": "string",
                    "enum": ["horizontal", "vertical"],
                    "default": "horizontal",
                    "title": "边缘方向",
                },
                "min_gap_pixels_to_count": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 2,
                    "title": "计入缺口的最小像素长度",
                },
                "max_gap_pixels": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "title": "最大允许缺口长度",
                },
                "max_gap_count": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "title": "最大允许缺口数量",
                },
                "min_axis_occupancy_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最小轴向占用率",
                },
            },
        },
        capability_tags=("vision.defect", "inspection.edge.profile", "inspection.edge.gap"),
    ),
    handler=_edge_profile_gap_check_handler,
)
