"""参考图差异 / 表面异常语义节点共享 helper。"""

from __future__ import annotations

from statistics import median

import numpy as np

from backend.nodes.core_nodes._region_node_support import (
    build_class_distribution,
    build_region_binary_mask,
    require_regions_payload,
    resolve_region_canvas_size,
)
from backend.nodes.core_nodes._roi_node_support import (
    build_roi_mask,
    require_roi_payload,
    resolve_roi_canvas_size,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def require_optional_roi_payload(payload: object, *, node_id: str | None = None) -> dict[str, object] | None:
    """读取可选 roi.v1 payload。"""

    if payload is None:
        return None
    return require_roi_payload(payload, node_id=node_id)


def compute_reference_diff_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    roi_payload: dict[str, object] | None,
) -> dict[str, object]:
    """把差异 regions 汇总为更贴工业现场的面积 / 占比 / 数量指标。"""

    if roi_payload is None:
        image_width, image_height = resolve_region_canvas_size(
            request,
            regions_payload=regions_payload,
        )
        scope_mask = np.ones((image_height, image_width), dtype=np.uint8)
        scope_kind = "image"
        scope_id = None
    else:
        image_width, image_height = resolve_roi_canvas_size(
            request,
            regions_payload=regions_payload,
            roi_payload=roi_payload,
        )
        scope_mask = build_roi_mask(
            roi_payload=roi_payload,
            image_width=image_width,
            image_height=image_height,
        )
        scope_kind = "roi"
        scope_id = str(roi_payload["roi_id"])
    scope_area = int(np.count_nonzero(scope_mask))
    union_mask = np.zeros((image_height, image_width), dtype=np.uint8)
    active_items: list[dict[str, object]] = []
    ignored_region_ids: list[str] = []
    effective_areas: list[int] = []
    for region_item in regions_payload["items"]:
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        mask_area = int(np.count_nonzero(region_mask))
        effective_mask = (
            region_mask
            if roi_payload is None
            else np.logical_and(region_mask > 0, scope_mask > 0).astype(np.uint8)
        )
        effective_area = int(np.count_nonzero(effective_mask))
        region_id = str(region_item["region_id"])
        if effective_area <= 0:
            ignored_region_ids.append(region_id)
            continue
        union_mask = np.maximum(union_mask, effective_mask)
        effective_areas.append(effective_area)
        active_items.append(
            {
                "region_id": region_id,
                "class_id": region_item.get("class_id"),
                "class_name": region_item.get("class_name"),
                "prompt_id": region_item.get("prompt_id"),
                "track_id": region_item.get("track_id"),
                "state": region_item.get("state"),
                "score": float(region_item["score"]),
                "declared_area": int(region_item["area"]),
                "mask_area": mask_area,
                "effective_area": effective_area,
                "effective_area_ratio": float(effective_area / scope_area) if scope_area > 0 else 0.0,
                "inside_scope_ratio": float(effective_area / mask_area) if mask_area > 0 else 0.0,
            }
        )
    total_diff_area = int(np.count_nonzero(union_mask))
    largest_diff_area = max(effective_areas) if effective_areas else 0
    avg_diff_area = float(sum(effective_areas) / len(effective_areas)) if effective_areas else 0.0
    median_diff_area = float(median(effective_areas)) if effective_areas else 0.0
    return {
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "scope_area": scope_area,
        "image_width": image_width,
        "image_height": image_height,
        "input_region_count": len(regions_payload["items"]),
        "active_region_count": len(active_items),
        "ignored_region_count": len(ignored_region_ids),
        "ignored_region_ids": ignored_region_ids,
        "active_region_ids": [item["region_id"] for item in active_items],
        "class_distribution": build_class_distribution(active_items),
        "sum_effective_area": int(sum(effective_areas)),
        "union_overlap_area": int(sum(effective_areas) - total_diff_area),
        "total_diff_area": total_diff_area,
        "total_diff_area_ratio": float(total_diff_area / scope_area) if scope_area > 0 else 0.0,
        "largest_diff_area": largest_diff_area,
        "largest_diff_area_ratio": float(largest_diff_area / scope_area) if scope_area > 0 else 0.0,
        "avg_diff_area": avg_diff_area,
        "avg_diff_area_ratio": float(avg_diff_area / scope_area) if scope_area > 0 else 0.0,
        "median_diff_area": median_diff_area,
        "median_diff_area_ratio": float(median_diff_area / scope_area) if scope_area > 0 else 0.0,
        "items": active_items,
    }


def read_optional_non_negative_int(
    raw_value: object,
    *,
    field_name: str,
    node_name: str,
) -> int | None:
    """读取可选非负整数参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须大于等于 0")
    return int(raw_value)


def read_optional_ratio(
    raw_value: object,
    *,
    field_name: str,
    node_name: str,
) -> float | None:
    """读取可选 0 到 1 范围比例参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是数值")
    normalized_value = float(raw_value)
    if normalized_value < 0.0 or normalized_value > 1.0:
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须在 0 到 1 之间")
    return normalized_value


def require_regions_with_optional_roi(
    request: WorkflowNodeExecutionRequest,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """读取差异语义节点统一输入。"""

    regions_payload = require_regions_payload(
        request.input_values.get("regions"),
        node_id=request.node_id,
    )
    roi_payload = require_optional_roi_payload(
        request.input_values.get("roi"),
        node_id=request.node_id,
    )
    return regions_payload, roi_payload


__all__ = [
    "compute_reference_diff_metrics",
    "read_optional_non_negative_int",
    "read_optional_ratio",
    "require_optional_roi_payload",
    "require_regions_with_optional_roi",
]
