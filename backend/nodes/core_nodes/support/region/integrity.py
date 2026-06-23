"""regions.v1 完整性、连通域和跨度指标。"""

from __future__ import annotations

import numpy as np

from backend.nodes.core_nodes.support.region.components import (
    compute_component_areas,
    compute_hole_areas,
    compute_span_metrics,
)
from backend.nodes.core_nodes.support.region.masks import (
    build_region_binary_mask,
    resolve_region_canvas_size,
)
from backend.nodes.core_nodes.support.region.metadata import (
    normalize_optional_int,
    normalize_optional_text,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def compute_regions_integrity_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
) -> dict[str, object]:
    """计算 regions.v1 的连通域、主体占比和空洞原子指标。"""

    image_width, image_height = resolve_region_canvas_size(
        request,
        regions_payload=regions_payload,
    )
    metrics_items: list[dict[str, object]] = []
    for region_item in regions_payload["items"]:
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        mask_area = int(np.count_nonzero(region_mask))
        component_areas = compute_component_areas(region_mask)
        hole_areas = compute_hole_areas(region_mask)
        largest_component_area = component_areas[0] if component_areas else 0
        largest_component_ratio = float(largest_component_area / mask_area) if mask_area > 0 else 0.0
        metrics_items.append(
            {
                "region_id": str(region_item["region_id"]),
                "class_id": normalize_optional_int(region_item.get("class_id")),
                "class_name": normalize_optional_text(region_item.get("class_name")),
                "prompt_id": normalize_optional_text(region_item.get("prompt_id")),
                "track_id": normalize_optional_text(region_item.get("track_id")),
                "state": normalize_optional_text(region_item.get("state")),
                "score": float(region_item["score"]),
                "declared_area": int(region_item["area"]),
                "mask_area": mask_area,
                "component_count": len(component_areas),
                "component_areas": component_areas,
                "largest_component_area": largest_component_area,
                "largest_component_ratio": largest_component_ratio,
                "hole_count": len(hole_areas),
                "hole_areas": hole_areas,
            }
        )
    return {
        "count": len(metrics_items),
        "image_width": image_width,
        "image_height": image_height,
        "items": metrics_items,
    }


def compute_regions_span_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
) -> dict[str, object]:
    """计算 regions.v1 的跨度、主方向和细长度等量测指标。"""

    image_width, image_height = resolve_region_canvas_size(
        request,
        regions_payload=regions_payload,
    )
    metrics_items: list[dict[str, object]] = []
    for region_item in regions_payload["items"]:
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        mask_area = int(np.count_nonzero(region_mask))
        span_metrics = compute_span_metrics(region_mask)
        metrics_items.append(
            {
                "region_id": str(region_item["region_id"]),
                "class_id": normalize_optional_int(region_item.get("class_id")),
                "class_name": normalize_optional_text(region_item.get("class_name")),
                "prompt_id": normalize_optional_text(region_item.get("prompt_id")),
                "track_id": normalize_optional_text(region_item.get("track_id")),
                "state": normalize_optional_text(region_item.get("state")),
                "score": float(region_item["score"]),
                "declared_area": int(region_item["area"]),
                "mask_area": mask_area,
                **span_metrics,
            }
        )
    return {
        "count": len(metrics_items),
        "image_width": image_width,
        "image_height": image_height,
        "items": metrics_items,
    }

