"""OpenCV 缺陷节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_nodes.categories.defect.backend.nodes.absdiff_threshold import (
    NODE_TYPE_ID as ABSDIFF_THRESHOLD_NODE_TYPE_ID,
    handle_node as absdiff_threshold_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.connected_components import (
    NODE_TYPE_ID as CONNECTED_COMPONENTS_NODE_TYPE_ID,
    handle_node as connected_components_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.distance_transform import (
    NODE_TYPE_ID as DISTANCE_TRANSFORM_NODE_TYPE_ID,
    handle_node as distance_transform_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.fill_holes import (
    NODE_TYPE_ID as FILL_HOLES_NODE_TYPE_ID,
    handle_node as fill_holes_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.image_diff import (
    NODE_TYPE_ID as IMAGE_DIFF_NODE_TYPE_ID,
    handle_node as image_diff_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.heatmap_preview import (
    NODE_TYPE_ID as HEATMAP_PREVIEW_NODE_TYPE_ID,
    handle_node as heatmap_preview_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.skeletonize import (
    NODE_TYPE_ID as SKELETONIZE_NODE_TYPE_ID,
    handle_node as skeletonize_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.watershed import (
    NODE_TYPE_ID as WATERSHED_NODE_TYPE_ID,
    handle_node as watershed_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.industrial_inspection import (
    INDUSTRIAL_INSPECTION_NODE_HANDLERS,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.clear_border import (
    NODE_TYPE_ID as CLEAR_BORDER_NODE_TYPE_ID,
    handle_node as clear_border_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.flood_fill import (
    NODE_TYPE_ID as FLOOD_FILL_NODE_TYPE_ID,
    handle_node as flood_fill_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.grabcut import (
    NODE_TYPE_ID as GRABCUT_NODE_TYPE_ID,
    handle_node as grabcut_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.kmeans_segment import (
    NODE_TYPE_ID as KMEANS_SEGMENT_NODE_TYPE_ID,
    handle_node as kmeans_segment_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.morphology_hitmiss import (
    NODE_TYPE_ID as MORPHOLOGY_HITMISS_NODE_TYPE_ID,
    handle_node as morphology_hitmiss_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.region_difference import (
    NODE_TYPE_ID as REGION_DIFFERENCE_NODE_TYPE_ID,
    handle_node as region_difference_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.region_intersection import (
    NODE_TYPE_ID as REGION_INTERSECTION_NODE_TYPE_ID,
    handle_node as region_intersection_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.region_union import (
    NODE_TYPE_ID as REGION_UNION_NODE_TYPE_ID,
    handle_node as region_union_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.remove_small_components import (
    NODE_TYPE_ID as REMOVE_SMALL_COMPONENTS_NODE_TYPE_ID,
    handle_node as remove_small_components_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.watershed_markers import (
    NODE_TYPE_ID as WATERSHED_MARKERS_NODE_TYPE_ID,
    handle_node as watershed_markers_handler,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.variation_model import (
    VARIATION_MODEL_NODE_HANDLERS,
)


NODE_HANDLERS = (
    (IMAGE_DIFF_NODE_TYPE_ID, image_diff_handler),
    (ABSDIFF_THRESHOLD_NODE_TYPE_ID, absdiff_threshold_handler),
    (CONNECTED_COMPONENTS_NODE_TYPE_ID, connected_components_handler),
    (FILL_HOLES_NODE_TYPE_ID, fill_holes_handler),
    (DISTANCE_TRANSFORM_NODE_TYPE_ID, distance_transform_handler),
    (HEATMAP_PREVIEW_NODE_TYPE_ID, heatmap_preview_handler),
    (WATERSHED_NODE_TYPE_ID, watershed_handler),
    (SKELETONIZE_NODE_TYPE_ID, skeletonize_handler),
    (FLOOD_FILL_NODE_TYPE_ID, flood_fill_handler),
    (GRABCUT_NODE_TYPE_ID, grabcut_handler),
    (KMEANS_SEGMENT_NODE_TYPE_ID, kmeans_segment_handler),
    (WATERSHED_MARKERS_NODE_TYPE_ID, watershed_markers_handler),
    (REMOVE_SMALL_COMPONENTS_NODE_TYPE_ID, remove_small_components_handler),
    (CLEAR_BORDER_NODE_TYPE_ID, clear_border_handler),
    (REGION_UNION_NODE_TYPE_ID, region_union_handler),
    (REGION_INTERSECTION_NODE_TYPE_ID, region_intersection_handler),
    (REGION_DIFFERENCE_NODE_TYPE_ID, region_difference_handler),
    (MORPHOLOGY_HITMISS_NODE_TYPE_ID, morphology_hitmiss_handler),
    *INDUSTRIAL_INSPECTION_NODE_HANDLERS,
    *VARIATION_MODEL_NODE_HANDLERS,
)


__all__ = ["NODE_HANDLERS"]
