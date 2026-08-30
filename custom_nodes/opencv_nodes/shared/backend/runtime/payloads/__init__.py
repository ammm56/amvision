"""OpenCV shared payload 构造和规范化入口。"""

from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.circles import (
    build_circles_payload,
    require_circles_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.calibrations import (
    require_camera_calibration_payload,
    require_stereo_calibration_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.contours import (
    build_contours_payload,
    require_contours_payload,
    resolve_contours_source_image,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.detections import (
    build_detection_label,
    iter_detection_items,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.images import (
    require_image_refs_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.ellipses import (
    build_ellipses_payload,
    require_ellipses_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.lines import (
    build_lines_payload,
    require_lines_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.localizations import (
    build_localizations_payload,
    require_localizations_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.points import (
    build_points_payload,
    require_points_payload,
)

__all__ = [
    "build_circles_payload",
    "build_contours_payload",
    "build_ellipses_payload",
    "build_localizations_payload",
    "build_detection_label",
    "build_lines_payload",
    "build_points_payload",
    "iter_detection_items",
    "require_circles_payload",
    "require_camera_calibration_payload",
    "require_contours_payload",
    "require_ellipses_payload",
    "require_image_refs_payload",
    "require_lines_payload",
    "require_localizations_payload",
    "require_points_payload",
    "require_stereo_calibration_payload",
    "resolve_contours_source_image",
]
