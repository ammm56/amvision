"""装配 / 对位类 core node 支撑函数。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.assembly.geometry import compute_bbox_center
from backend.nodes.core_nodes.support.assembly.parameters import (
    read_optional_non_negative_number,
    read_required_number,
)
from backend.nodes.core_nodes.support.assembly.selectors import (
    REGION_SELECTION_STRATEGY_ENUM,
    SUPPORTED_REGION_SELECTION_STRATEGIES,
    build_selector_summary,
    read_region_selection_strategy,
    read_region_selector,
    select_region_candidates,
    select_single_region_item,
)

__all__ = [
    "REGION_SELECTION_STRATEGY_ENUM",
    "SUPPORTED_REGION_SELECTION_STRATEGIES",
    "build_selector_summary",
    "compute_bbox_center",
    "read_optional_non_negative_number",
    "read_region_selection_strategy",
    "read_region_selector",
    "read_required_number",
    "select_region_candidates",
    "select_single_region_item",
]
