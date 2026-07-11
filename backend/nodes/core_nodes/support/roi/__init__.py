"""roi.v1 与 ROI 规则支撑函数包。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.region import (
    require_regions_payload,
    select_best_region_item,
)
from backend.nodes.core_nodes.support.roi.geometry import (
    bbox_area,
    bbox_to_polygon_xy,
    normalize_bbox_xyxy,
    normalize_polygon_xy,
    polygon_area,
    polygon_bbox_xyxy,
)
from backend.nodes.core_nodes.support.roi.intersections import (
    compute_regions_intersection_metrics,
)
from backend.nodes.core_nodes.support.roi.masks import (
    build_region_mask,
    build_roi_mask,
    derive_canvas_size_from_payloads,
    resolve_roi_canvas_size,
)
from backend.nodes.core_nodes.support.roi.parameters import (
    read_optional_bool,
    read_optional_number,
    read_optional_text,
    read_polygon_parameter,
)
from backend.nodes.core_nodes.support.roi.payloads import (
    build_roi_list_payload,
    build_roi_payload,
    iter_roi_payloads,
    require_roi_list_payload,
    require_roi_payload,
)

__all__ = [
    "bbox_area",
    "bbox_to_polygon_xy",
    "build_region_mask",
    "build_roi_mask",
    "build_roi_list_payload",
    "build_roi_payload",
    "compute_regions_intersection_metrics",
    "derive_canvas_size_from_payloads",
    "iter_roi_payloads",
    "normalize_bbox_xyxy",
    "normalize_polygon_xy",
    "polygon_area",
    "polygon_bbox_xyxy",
    "read_optional_bool",
    "read_optional_number",
    "read_optional_text",
    "read_polygon_parameter",
    "require_regions_payload",
    "require_roi_list_payload",
    "require_roi_payload",
    "resolve_roi_canvas_size",
    "select_best_region_item",
]
