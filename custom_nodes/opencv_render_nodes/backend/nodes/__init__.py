"""OpenCV 渲染节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_render_nodes.backend.nodes.draw_circles import (
    NODE_TYPE_ID as DRAW_CIRCLES_NODE_TYPE_ID,
    handle_node as draw_circles_handler,
)
from custom_nodes.opencv_render_nodes.backend.nodes.draw_contours import (
    NODE_TYPE_ID as DRAW_CONTOURS_NODE_TYPE_ID,
    handle_node as draw_contours_handler,
)
from custom_nodes.opencv_render_nodes.backend.nodes.draw_detections import (
    NODE_TYPE_ID as DRAW_DETECTIONS_NODE_TYPE_ID,
    handle_node as draw_detections_handler,
)
from custom_nodes.opencv_render_nodes.backend.nodes.draw_lines import (
    NODE_TYPE_ID as DRAW_LINES_NODE_TYPE_ID,
    handle_node as draw_lines_handler,
)
from custom_nodes.opencv_render_nodes.backend.nodes.draw_measurements import (
    NODE_TYPE_ID as DRAW_MEASUREMENTS_NODE_TYPE_ID,
    handle_node as draw_measurements_handler,
)
from custom_nodes.opencv_render_nodes.backend.nodes.draw_regions import (
    NODE_TYPE_ID as DRAW_REGIONS_NODE_TYPE_ID,
    handle_node as draw_regions_handler,
)
from custom_nodes.opencv_render_nodes.backend.nodes.draw_roi import (
    NODE_TYPE_ID as DRAW_ROI_NODE_TYPE_ID,
    handle_node as draw_roi_handler,
)
from custom_nodes.opencv_render_nodes.backend.nodes.draw_rois import (
    NODE_TYPE_ID as DRAW_ROIS_NODE_TYPE_ID,
    handle_node as draw_rois_handler,
)


NODE_HANDLERS = (
    (DRAW_CIRCLES_NODE_TYPE_ID, draw_circles_handler),
    (DRAW_CONTOURS_NODE_TYPE_ID, draw_contours_handler),
    (DRAW_DETECTIONS_NODE_TYPE_ID, draw_detections_handler),
    (DRAW_LINES_NODE_TYPE_ID, draw_lines_handler),
    (DRAW_MEASUREMENTS_NODE_TYPE_ID, draw_measurements_handler),
    (DRAW_REGIONS_NODE_TYPE_ID, draw_regions_handler),
    (DRAW_ROI_NODE_TYPE_ID, draw_roi_handler),
    (DRAW_ROIS_NODE_TYPE_ID, draw_rois_handler),
)


__all__ = ["NODE_HANDLERS"]
