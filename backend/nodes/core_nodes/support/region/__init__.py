"""regions.v1 支撑函数包。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.region.geometry import (
    compute_region_bbox_metrics,
    compute_regions_circularity_metrics,
    compute_regions_linearity_metrics,
)
from backend.nodes.core_nodes.support.region.images import (
    resolve_region_source_image_payload,
    resolve_region_source_image_size,
)
from backend.nodes.core_nodes.support.region.integrity import (
    compute_regions_integrity_metrics,
    compute_regions_span_metrics,
)
from backend.nodes.core_nodes.support.region.masks import (
    build_bbox_mask,
    build_polygon_mask,
    build_region_binary_mask,
    derive_region_canvas_size,
    resolve_region_canvas_size,
)
from backend.nodes.core_nodes.support.region.payloads import (
    build_class_distribution,
    build_regions_payload,
    build_score_summary,
    filter_region_items,
    read_optional_int,
    read_optional_int_set,
    read_optional_number,
    read_optional_str_set,
    select_best_region_item,
)
from backend.nodes.core_nodes.support.video_track import require_regions_payload

__all__ = [
    "build_bbox_mask",
    "build_class_distribution",
    "build_polygon_mask",
    "build_region_binary_mask",
    "build_regions_payload",
    "build_score_summary",
    "compute_region_bbox_metrics",
    "compute_regions_circularity_metrics",
    "compute_regions_integrity_metrics",
    "compute_regions_linearity_metrics",
    "compute_regions_span_metrics",
    "derive_region_canvas_size",
    "filter_region_items",
    "read_optional_int",
    "read_optional_int_set",
    "read_optional_number",
    "read_optional_str_set",
    "require_regions_payload",
    "resolve_region_canvas_size",
    "resolve_region_source_image_payload",
    "resolve_region_source_image_size",
    "select_best_region_item",
]

