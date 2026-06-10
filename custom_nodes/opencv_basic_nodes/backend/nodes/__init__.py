"""OpenCV 基础节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_basic_nodes.backend.nodes.adaptive_threshold import (
    NODE_TYPE_ID as ADAPTIVE_THRESHOLD_NODE_TYPE_ID,
    handle_node as adaptive_threshold_handler,
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
from custom_nodes.opencv_basic_nodes.backend.nodes.clahe import (
    NODE_TYPE_ID as CLAHE_NODE_TYPE_ID,
    handle_node as clahe_handler,
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
from custom_nodes.opencv_basic_nodes.backend.nodes.gallery_preview import (
    NODE_TYPE_ID as GALLERY_PREVIEW_NODE_TYPE_ID,
    handle_node as gallery_preview_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.gaussian_blur import (
    NODE_TYPE_ID as GAUSSIAN_BLUR_NODE_TYPE_ID,
    handle_node as gaussian_blur_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.grayscale import (
    NODE_TYPE_ID as GRAYSCALE_NODE_TYPE_ID,
    handle_node as grayscale_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.invert import (
    NODE_TYPE_ID as INVERT_NODE_TYPE_ID,
    handle_node as invert_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.laplacian import (
    NODE_TYPE_ID as LAPLACIAN_NODE_TYPE_ID,
    handle_node as laplacian_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.median_blur import (
    NODE_TYPE_ID as MEDIAN_BLUR_NODE_TYPE_ID,
    handle_node as median_blur_handler,
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
from custom_nodes.opencv_basic_nodes.backend.nodes.payload_to_value import (
    NODE_TYPE_ID as PAYLOAD_TO_VALUE_NODE_TYPE_ID,
    handle_node as payload_to_value_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.resize import (
    NODE_TYPE_ID as RESIZE_NODE_TYPE_ID,
    handle_node as resize_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.sobel import (
    NODE_TYPE_ID as SOBEL_NODE_TYPE_ID,
    handle_node as sobel_handler,
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
    (PAYLOAD_TO_VALUE_NODE_TYPE_ID, payload_to_value_handler),
    (CROP_EXPORT_NODE_TYPE_ID, crop_export_handler),
    (GALLERY_PREVIEW_NODE_TYPE_ID, gallery_preview_handler),
    (GRAYSCALE_NODE_TYPE_ID, grayscale_handler),
    (LAPLACIAN_NODE_TYPE_ID, laplacian_handler),
    (RESIZE_NODE_TYPE_ID, resize_handler),
    (INVERT_NODE_TYPE_ID, invert_handler),
    (MEDIAN_BLUR_NODE_TYPE_ID, median_blur_handler),
    (NORMALIZE_NODE_TYPE_ID, normalize_handler),
    (ADAPTIVE_THRESHOLD_NODE_TYPE_ID, adaptive_threshold_handler),
    (OTSU_THRESHOLD_NODE_TYPE_ID, otsu_threshold_handler),
    (SOBEL_NODE_TYPE_ID, sobel_handler),
    (TEMPLATE_MATCH_NODE_TYPE_ID, template_match_handler),
)


__all__ = ["NODE_HANDLERS"]
