"""YOLO11 target 编码入口。"""

from __future__ import annotations

from backend.service.application.models.yolo11_core.targets.detection import (
    yolo11_bbox_xyxy_to_distances,
)
from backend.service.application.models.yolo11_core.targets.obb import (
    yolo11_anchor_in_rotated_box,
    yolo11_decode_distances_to_rboxes,
    yolo11_rbox_to_distances,
    yolo11_scale_rbox_to_grid,
    yolo11_xywhr_to_corners,
    yolo11_xywhr_to_xyxy,
)
from backend.service.application.models.yolo11_core.targets.pose import (
    normalize_yolo11_gt_keypoints_tensor,
)
from backend.service.application.models.yolo11_core.targets.segmentation import (
    rasterize_yolo11_segmentation_polygons,
    select_yolo11_object_segmentation_polygons,
)

__all__ = [
    "normalize_yolo11_gt_keypoints_tensor",
    "rasterize_yolo11_segmentation_polygons",
    "select_yolo11_object_segmentation_polygons",
    "yolo11_anchor_in_rotated_box",
    "yolo11_bbox_xyxy_to_distances",
    "yolo11_decode_distances_to_rboxes",
    "yolo11_rbox_to_distances",
    "yolo11_scale_rbox_to_grid",
    "yolo11_xywhr_to_corners",
    "yolo11_xywhr_to_xyxy",
]
