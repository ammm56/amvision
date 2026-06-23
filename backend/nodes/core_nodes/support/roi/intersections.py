"""regions 与 ROI 的交集指标计算。"""

from __future__ import annotations

from typing import Any

import numpy as np

from backend.nodes.core_nodes.support.roi.masks import (
    build_region_mask,
    build_roi_mask,
    resolve_roi_canvas_size,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def compute_regions_intersection_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    roi_payload: dict[str, object],
) -> dict[str, object]:
    """计算 regions 与 ROI 的交集、覆盖率和 IoU 指标。"""

    image_width, image_height = resolve_roi_canvas_size(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    roi_mask = build_roi_mask(
        roi_payload=roi_payload,
        image_width=image_width,
        image_height=image_height,
    )
    roi_area = int(np.count_nonzero(roi_mask))
    union_region_mask = np.zeros_like(roi_mask)
    metrics_items: list[dict[str, Any]] = []
    best_iou = 0.0
    best_inside_ratio = 0.0
    for region_item in regions_payload["items"]:
        region_mask = build_region_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        union_region_mask = np.maximum(union_region_mask, region_mask)
        region_area = max(0, int(region_item["area"]))
        intersection_area = int(np.count_nonzero(np.logical_and(region_mask > 0, roi_mask > 0)))
        mask_region_area = int(np.count_nonzero(region_mask))
        effective_region_area = max(region_area, mask_region_area)
        union_area = effective_region_area + roi_area - intersection_area
        inside_ratio = float(intersection_area / effective_region_area) if effective_region_area > 0 else 0.0
        roi_coverage_ratio = float(intersection_area / roi_area) if roi_area > 0 else 0.0
        iou_ratio = float(intersection_area / union_area) if union_area > 0 else 0.0
        best_iou = max(best_iou, iou_ratio)
        best_inside_ratio = max(best_inside_ratio, inside_ratio)
        metrics_items.append(
            {
                "region_id": region_item["region_id"],
                "class_id": region_item.get("class_id"),
                "class_name": region_item.get("class_name"),
                "prompt_id": region_item.get("prompt_id"),
                "track_id": region_item.get("track_id"),
                "state": region_item.get("state"),
                "region_area": effective_region_area,
                "intersection_area": intersection_area,
                "roi_coverage_ratio": roi_coverage_ratio,
                "inside_ratio": inside_ratio,
                "iou": iou_ratio,
            }
        )
    union_region_area = int(np.count_nonzero(union_region_mask))
    union_intersection_area = int(np.count_nonzero(np.logical_and(union_region_mask > 0, roi_mask > 0)))
    return {
        "roi_id": roi_payload["roi_id"],
        "roi_kind": roi_payload["roi_kind"],
        "roi_area": roi_area,
        "region_count": len(regions_payload["items"]),
        "image_width": image_width,
        "image_height": image_height,
        "union_region_area": union_region_area,
        "union_intersection_area": union_intersection_area,
        "roi_coverage_ratio": float(union_intersection_area / roi_area) if roi_area > 0 else 0.0,
        "region_inside_ratio": float(union_intersection_area / union_region_area) if union_region_area > 0 else 0.0,
        "best_iou": best_iou,
        "best_inside_ratio": best_inside_ratio,
        "items": metrics_items,
    }

