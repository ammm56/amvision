"""YOLO26 target 编码入口。"""

from __future__ import annotations

from backend.service.application.models.yolo26_core.targets.detection import (
    yolo26_bbox_xyxy_to_distances,
)
from backend.service.application.models.yolo26_core.targets.obb import (
    yolo26_anchor_in_rotated_box,
    yolo26_decode_distances_to_rboxes,
    yolo26_rbox_to_distances,
    yolo26_scale_rbox_to_grid,
    yolo26_xywhr_to_corners,
    yolo26_xywhr_to_xyxy,
)
from backend.service.application.models.yolo26_core.targets.pose import (
    normalize_yolo26_gt_keypoints_tensor,
)
from backend.service.application.models.yolo26_core.targets.segmentation import (
    rasterize_yolo26_segmentation_polygons,
    select_yolo26_object_segmentation_polygons,
)

__all__ = [
    "normalize_yolo26_gt_keypoints_tensor",
    "rasterize_yolo26_segmentation_polygons",
    "select_yolo26_object_segmentation_polygons",
    "yolo26_anchor_in_rotated_box",
    "yolo26_bbox_xyxy_to_distances",
    "yolo26_decode_distances_to_rboxes",
    "yolo26_rbox_to_distances",
    "yolo26_scale_rbox_to_grid",
    "yolo26_xywhr_to_corners",
    "yolo26_xywhr_to_xyxy",
]
