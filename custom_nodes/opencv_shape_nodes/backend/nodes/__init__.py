"""OpenCV 形状节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_shape_nodes.backend.nodes.contour import (
    NODE_TYPE_ID as CONTOUR_NODE_TYPE_ID,
    handle_node as contour_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.circle_measure import (
    NODE_TYPE_ID as CIRCLE_MEASURE_NODE_TYPE_ID,
    handle_node as circle_measure_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.contour_approx import (
    NODE_TYPE_ID as CONTOUR_APPROX_NODE_TYPE_ID,
    handle_node as contour_approx_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.contour_filter import (
    NODE_TYPE_ID as CONTOUR_FILTER_NODE_TYPE_ID,
    handle_node as contour_filter_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.contours_to_regions import (
    NODE_TYPE_ID as CONTOURS_TO_REGIONS_NODE_TYPE_ID,
    handle_node as contours_to_regions_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.convex_hull import (
    NODE_TYPE_ID as CONVEX_HULL_NODE_TYPE_ID,
    handle_node as convex_hull_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.fit_ellipse import (
    NODE_TYPE_ID as FIT_ELLIPSE_NODE_TYPE_ID,
    handle_node as fit_ellipse_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.fit_line import (
    NODE_TYPE_ID as FIT_LINE_NODE_TYPE_ID,
    handle_node as fit_line_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.hough_circles import (
    NODE_TYPE_ID as HOUGH_CIRCLES_NODE_TYPE_ID,
    handle_node as hough_circles_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.hough_lines import (
    NODE_TYPE_ID as HOUGH_LINES_NODE_TYPE_ID,
    handle_node as hough_lines_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.min_area_rect import (
    NODE_TYPE_ID as MIN_AREA_RECT_NODE_TYPE_ID,
    handle_node as min_area_rect_handler,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.min_enclosing_circle import (
    NODE_TYPE_ID as MIN_ENCLOSING_CIRCLE_NODE_TYPE_ID,
    handle_node as min_enclosing_circle_handler,
)


NODE_HANDLERS = (
    (CIRCLE_MEASURE_NODE_TYPE_ID, circle_measure_handler),
    (CONTOUR_NODE_TYPE_ID, contour_handler),
    (CONTOUR_APPROX_NODE_TYPE_ID, contour_approx_handler),
    (CONTOUR_FILTER_NODE_TYPE_ID, contour_filter_handler),
    (CONTOURS_TO_REGIONS_NODE_TYPE_ID, contours_to_regions_handler),
    (CONVEX_HULL_NODE_TYPE_ID, convex_hull_handler),
    (FIT_ELLIPSE_NODE_TYPE_ID, fit_ellipse_handler),
    (FIT_LINE_NODE_TYPE_ID, fit_line_handler),
    (HOUGH_CIRCLES_NODE_TYPE_ID, hough_circles_handler),
    (HOUGH_LINES_NODE_TYPE_ID, hough_lines_handler),
    (MIN_AREA_RECT_NODE_TYPE_ID, min_area_rect_handler),
    (MIN_ENCLOSING_CIRCLE_NODE_TYPE_ID, min_enclosing_circle_handler),
)


__all__ = ["NODE_HANDLERS"]
