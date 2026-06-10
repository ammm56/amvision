"""OpenCV 基础节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_basic_nodes.backend.nodes.adaptive_threshold import (
    NODE_TYPE_ID as ADAPTIVE_THRESHOLD_NODE_TYPE_ID,
    handle_node as adaptive_threshold_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.absdiff_threshold import (
    NODE_TYPE_ID as ABSDIFF_THRESHOLD_NODE_TYPE_ID,
    handle_node as absdiff_threshold_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.binary_threshold import (
    NODE_TYPE_ID as BINARY_THRESHOLD_NODE_TYPE_ID,
    handle_node as binary_threshold_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.canny import (
    NODE_TYPE_ID as CANNY_NODE_TYPE_ID,
    handle_node as canny_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.bilateral_filter import (
    NODE_TYPE_ID as BILATERAL_FILTER_NODE_TYPE_ID,
    handle_node as bilateral_filter_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.caliper_edge import (
    NODE_TYPE_ID as CALIPER_EDGE_NODE_TYPE_ID,
    handle_node as caliper_edge_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.clahe import (
    NODE_TYPE_ID as CLAHE_NODE_TYPE_ID,
    handle_node as clahe_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.circle_diameter import (
    NODE_TYPE_ID as CIRCLE_DIAMETER_NODE_TYPE_ID,
    handle_node as circle_diameter_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.contour import (
    NODE_TYPE_ID as CONTOUR_NODE_TYPE_ID,
    handle_node as contour_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.contour_filter import (
    NODE_TYPE_ID as CONTOUR_FILTER_NODE_TYPE_ID,
    handle_node as contour_filter_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.contours_to_regions import (
    NODE_TYPE_ID as CONTOURS_TO_REGIONS_NODE_TYPE_ID,
    handle_node as contours_to_regions_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.connected_components import (
    NODE_TYPE_ID as CONNECTED_COMPONENTS_NODE_TYPE_ID,
    handle_node as connected_components_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.contour_approx import (
    NODE_TYPE_ID as CONTOUR_APPROX_NODE_TYPE_ID,
    handle_node as contour_approx_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.concentricity_metrics import (
    NODE_TYPE_ID as CONCENTRICITY_METRICS_NODE_TYPE_ID,
    handle_node as concentricity_metrics_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.convex_hull import (
    NODE_TYPE_ID as CONVEX_HULL_NODE_TYPE_ID,
    handle_node as convex_hull_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.crop_export import (
    NODE_TYPE_ID as CROP_EXPORT_NODE_TYPE_ID,
    handle_node as crop_export_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.crop import (
    NODE_TYPE_ID as CROP_NODE_TYPE_ID,
    handle_node as crop_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.draw_detections import (
    NODE_TYPE_ID as DRAW_DETECTIONS_NODE_TYPE_ID,
    handle_node as draw_detections_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.draw_circles import (
    NODE_TYPE_ID as DRAW_CIRCLES_NODE_TYPE_ID,
    handle_node as draw_circles_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.draw_contours import (
    NODE_TYPE_ID as DRAW_CONTOURS_NODE_TYPE_ID,
    handle_node as draw_contours_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.draw_lines import (
    NODE_TYPE_ID as DRAW_LINES_NODE_TYPE_ID,
    handle_node as draw_lines_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.draw_measurements import (
    NODE_TYPE_ID as DRAW_MEASUREMENTS_NODE_TYPE_ID,
    handle_node as draw_measurements_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.draw_roi import (
    NODE_TYPE_ID as DRAW_ROI_NODE_TYPE_ID,
    handle_node as draw_roi_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.distance_transform import (
    NODE_TYPE_ID as DISTANCE_TRANSFORM_NODE_TYPE_ID,
    handle_node as distance_transform_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.fill_holes import (
    NODE_TYPE_ID as FILL_HOLES_NODE_TYPE_ID,
    handle_node as fill_holes_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.gallery_preview import (
    NODE_TYPE_ID as GALLERY_PREVIEW_NODE_TYPE_ID,
    handle_node as gallery_preview_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.fit_ellipse import (
    NODE_TYPE_ID as FIT_ELLIPSE_NODE_TYPE_ID,
    handle_node as fit_ellipse_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.gaussian_blur import (
    NODE_TYPE_ID as GAUSSIAN_BLUR_NODE_TYPE_ID,
    handle_node as gaussian_blur_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.grayscale import (
    NODE_TYPE_ID as GRAYSCALE_NODE_TYPE_ID,
    handle_node as grayscale_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.fit_line import (
    NODE_TYPE_ID as FIT_LINE_NODE_TYPE_ID,
    handle_node as fit_line_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.hough_circles import (
    NODE_TYPE_ID as HOUGH_CIRCLES_NODE_TYPE_ID,
    handle_node as hough_circles_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.hough_lines import (
    NODE_TYPE_ID as HOUGH_LINES_NODE_TYPE_ID,
    handle_node as hough_lines_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.image_diff import (
    NODE_TYPE_ID as IMAGE_DIFF_NODE_TYPE_ID,
    handle_node as image_diff_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.invert import (
    NODE_TYPE_ID as INVERT_NODE_TYPE_ID,
    handle_node as invert_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.line_angle import (
    NODE_TYPE_ID as LINE_ANGLE_NODE_TYPE_ID,
    handle_node as line_angle_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.measure import (
    NODE_TYPE_ID as MEASURE_NODE_TYPE_ID,
    handle_node as measure_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.median_blur import (
    NODE_TYPE_ID as MEDIAN_BLUR_NODE_TYPE_ID,
    handle_node as median_blur_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.min_area_rect import (
    NODE_TYPE_ID as MIN_AREA_RECT_NODE_TYPE_ID,
    handle_node as min_area_rect_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.min_enclosing_circle import (
    NODE_TYPE_ID as MIN_ENCLOSING_CIRCLE_NODE_TYPE_ID,
    handle_node as min_enclosing_circle_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.morphology import (
    NODE_TYPE_ID as MORPHOLOGY_NODE_TYPE_ID,
    handle_node as morphology_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.mask_overlay import (
    NODE_TYPE_ID as MASK_OVERLAY_NODE_TYPE_ID,
    handle_node as mask_overlay_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.normalize import (
    NODE_TYPE_ID as NORMALIZE_NODE_TYPE_ID,
    handle_node as normalize_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.otsu_threshold import (
    NODE_TYPE_ID as OTSU_THRESHOLD_NODE_TYPE_ID,
    handle_node as otsu_threshold_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.parallelism_metrics import (
    NODE_TYPE_ID as PARALLELISM_METRICS_NODE_TYPE_ID,
    handle_node as parallelism_metrics_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.payload_to_value import (
    NODE_TYPE_ID as PAYLOAD_TO_VALUE_NODE_TYPE_ID,
    handle_node as payload_to_value_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.point_distance import (
    NODE_TYPE_ID as POINT_DISTANCE_NODE_TYPE_ID,
    handle_node as point_distance_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.point_to_line_distance import (
    NODE_TYPE_ID as POINT_TO_LINE_DISTANCE_NODE_TYPE_ID,
    handle_node as point_to_line_distance_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.resize import (
    NODE_TYPE_ID as RESIZE_NODE_TYPE_ID,
    handle_node as resize_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.rotation_correct import (
    NODE_TYPE_ID as ROTATION_CORRECT_NODE_TYPE_ID,
    handle_node as rotation_correct_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.slot_width import (
    NODE_TYPE_ID as SLOT_WIDTH_NODE_TYPE_ID,
    handle_node as slot_width_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.template_match import (
    NODE_TYPE_ID as TEMPLATE_MATCH_NODE_TYPE_ID,
    handle_node as template_match_handler,
)


NODE_HANDLERS = (
    (DRAW_DETECTIONS_NODE_TYPE_ID, draw_detections_handler),
    (DRAW_CIRCLES_NODE_TYPE_ID, draw_circles_handler),
    (DRAW_CONTOURS_NODE_TYPE_ID, draw_contours_handler),
    (DRAW_LINES_NODE_TYPE_ID, draw_lines_handler),
    (DRAW_ROI_NODE_TYPE_ID, draw_roi_handler),
    (DRAW_MEASUREMENTS_NODE_TYPE_ID, draw_measurements_handler),
    (MASK_OVERLAY_NODE_TYPE_ID, mask_overlay_handler),
    (BILATERAL_FILTER_NODE_TYPE_ID, bilateral_filter_handler),
    (CLAHE_NODE_TYPE_ID, clahe_handler),
    (CROP_NODE_TYPE_ID, crop_handler),
    (GAUSSIAN_BLUR_NODE_TYPE_ID, gaussian_blur_handler),
    (BINARY_THRESHOLD_NODE_TYPE_ID, binary_threshold_handler),
    (MORPHOLOGY_NODE_TYPE_ID, morphology_handler),
    (CANNY_NODE_TYPE_ID, canny_handler),
    (CALIPER_EDGE_NODE_TYPE_ID, caliper_edge_handler),
    (CIRCLE_DIAMETER_NODE_TYPE_ID, circle_diameter_handler),
    (CONCENTRICITY_METRICS_NODE_TYPE_ID, concentricity_metrics_handler),
    (CONTOUR_NODE_TYPE_ID, contour_handler),
    (CONTOUR_APPROX_NODE_TYPE_ID, contour_approx_handler),
    (CONVEX_HULL_NODE_TYPE_ID, convex_hull_handler),
    (LINE_ANGLE_NODE_TYPE_ID, line_angle_handler),
    (MEASURE_NODE_TYPE_ID, measure_handler),
    (PARALLELISM_METRICS_NODE_TYPE_ID, parallelism_metrics_handler),
    (PAYLOAD_TO_VALUE_NODE_TYPE_ID, payload_to_value_handler),
    (POINT_DISTANCE_NODE_TYPE_ID, point_distance_handler),
    (POINT_TO_LINE_DISTANCE_NODE_TYPE_ID, point_to_line_distance_handler),
    (CROP_EXPORT_NODE_TYPE_ID, crop_export_handler),
    (DISTANCE_TRANSFORM_NODE_TYPE_ID, distance_transform_handler),
    (FILL_HOLES_NODE_TYPE_ID, fill_holes_handler),
    (GALLERY_PREVIEW_NODE_TYPE_ID, gallery_preview_handler),
    (FIT_ELLIPSE_NODE_TYPE_ID, fit_ellipse_handler),
    (GRAYSCALE_NODE_TYPE_ID, grayscale_handler),
    (FIT_LINE_NODE_TYPE_ID, fit_line_handler),
    (HOUGH_LINES_NODE_TYPE_ID, hough_lines_handler),
    (HOUGH_CIRCLES_NODE_TYPE_ID, hough_circles_handler),
    (RESIZE_NODE_TYPE_ID, resize_handler),
    (INVERT_NODE_TYPE_ID, invert_handler),
    (MEDIAN_BLUR_NODE_TYPE_ID, median_blur_handler),
    (NORMALIZE_NODE_TYPE_ID, normalize_handler),
    (ADAPTIVE_THRESHOLD_NODE_TYPE_ID, adaptive_threshold_handler),
    (OTSU_THRESHOLD_NODE_TYPE_ID, otsu_threshold_handler),
    (CONTOUR_FILTER_NODE_TYPE_ID, contour_filter_handler),
    (MIN_AREA_RECT_NODE_TYPE_ID, min_area_rect_handler),
    (MIN_ENCLOSING_CIRCLE_NODE_TYPE_ID, min_enclosing_circle_handler),
    (CONTOURS_TO_REGIONS_NODE_TYPE_ID, contours_to_regions_handler),
    (IMAGE_DIFF_NODE_TYPE_ID, image_diff_handler),
    (ABSDIFF_THRESHOLD_NODE_TYPE_ID, absdiff_threshold_handler),
    (CONNECTED_COMPONENTS_NODE_TYPE_ID, connected_components_handler),
    (ROTATION_CORRECT_NODE_TYPE_ID, rotation_correct_handler),
    (SLOT_WIDTH_NODE_TYPE_ID, slot_width_handler),
    (TEMPLATE_MATCH_NODE_TYPE_ID, template_match_handler),
)


__all__ = ["NODE_HANDLERS"]
