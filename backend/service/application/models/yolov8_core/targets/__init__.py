"""YOLOv8 target 编码入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.targets.detection import (
    yolov8_bbox_xyxy_to_distances,
)
from backend.service.application.models.yolov8_core.targets.obb import (
    yolov8_anchor_in_rotated_box,
    yolov8_decode_distances_to_rboxes,
    yolov8_rbox_to_distances,
    yolov8_xywhr_to_corners,
)
from backend.service.application.models.yolov8_core.targets.pose import (
    normalize_yolov8_gt_keypoints_tensor,
)
from backend.service.application.models.yolov8_core.targets.segmentation import (
    rasterize_yolov8_segmentation_polygons,
    select_yolov8_object_segmentation_polygons,
)

__all__ = [
    "normalize_yolov8_gt_keypoints_tensor",
    "rasterize_yolov8_segmentation_polygons",
    "select_yolov8_object_segmentation_polygons",
    "yolov8_anchor_in_rotated_box",
    "yolov8_bbox_xyxy_to_distances",
    "yolov8_decode_distances_to_rboxes",
    "yolov8_rbox_to_distances",
    "yolov8_xywhr_to_corners",
]
