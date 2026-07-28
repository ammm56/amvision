"""OpenCV 形状节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_nodes.categories.shape.backend.nodes.contour import (
    NODE_TYPE_ID as CONTOUR_NODE_TYPE_ID,
    handle_node as contour_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.circle_measure import (
    NODE_TYPE_ID as CIRCLE_MEASURE_NODE_TYPE_ID,
    handle_node as circle_measure_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.contour_approx import (
    NODE_TYPE_ID as CONTOUR_APPROX_NODE_TYPE_ID,
    handle_node as contour_approx_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.contour_filter import (
    NODE_TYPE_ID as CONTOUR_FILTER_NODE_TYPE_ID,
    handle_node as contour_filter_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.contours_to_regions import (
    NODE_TYPE_ID as CONTOURS_TO_REGIONS_NODE_TYPE_ID,
    handle_node as contours_to_regions_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.convex_hull import (
    NODE_TYPE_ID as CONVEX_HULL_NODE_TYPE_ID,
    handle_node as convex_hull_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.fit_ellipse import (
    NODE_TYPE_ID as FIT_ELLIPSE_NODE_TYPE_ID,
    handle_node as fit_ellipse_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.fit_line import (
    NODE_TYPE_ID as FIT_LINE_NODE_TYPE_ID,
    handle_node as fit_line_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.hough_circles import (
    NODE_TYPE_ID as HOUGH_CIRCLES_NODE_TYPE_ID,
    handle_node as hough_circles_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.hough_lines import (
    NODE_TYPE_ID as HOUGH_LINES_NODE_TYPE_ID,
    handle_node as hough_lines_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.min_area_rect import (
    NODE_TYPE_ID as MIN_AREA_RECT_NODE_TYPE_ID,
    handle_node as min_area_rect_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.min_enclosing_circle import (
    NODE_TYPE_ID as MIN_ENCLOSING_CIRCLE_NODE_TYPE_ID,
    handle_node as min_enclosing_circle_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.convexity_defects import (
    NODE_TYPE_ID as CONVEXITY_DEFECTS_NODE_TYPE_ID,
    handle_node as convexity_defects_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.hu_moments import (
    NODE_TYPE_ID as HU_MOMENTS_NODE_TYPE_ID,
    handle_node as hu_moments_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.image_moments import (
    NODE_TYPE_ID as IMAGE_MOMENTS_NODE_TYPE_ID,
    handle_node as image_moments_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.point_polygon_test import (
    NODE_TYPE_ID as POINT_POLYGON_TEST_NODE_TYPE_ID,
    handle_node as point_polygon_test_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.region_properties import (
    NODE_TYPE_ID as REGION_PROPERTIES_NODE_TYPE_ID,
    handle_node as region_properties_handler,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes.shape_match import (
    NODE_TYPE_ID as SHAPE_MATCH_NODE_TYPE_ID,
    handle_node as shape_match_handler,
)


NODE_HANDLERS = (
    (REGION_PROPERTIES_NODE_TYPE_ID, region_properties_handler),
    (IMAGE_MOMENTS_NODE_TYPE_ID, image_moments_handler),
    (HU_MOMENTS_NODE_TYPE_ID, hu_moments_handler),
    (SHAPE_MATCH_NODE_TYPE_ID, shape_match_handler),
    (CONVEXITY_DEFECTS_NODE_TYPE_ID, convexity_defects_handler),
    (POINT_POLYGON_TEST_NODE_TYPE_ID, point_polygon_test_handler),
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
