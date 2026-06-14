"""YOLO 主线共用 target 编码入口。"""

from __future__ import annotations

from backend.service.application.models.yolo_core_common.targets.detection import (
    bbox_xyxy_to_distances,
)
from backend.service.application.models.yolo_core_common.targets.obb import (
    anchor_in_rotated_box,
    decode_distances_to_rboxes,
    rbox_to_distances,
    xywhr_to_corners,
    xywhr_to_xyxy,
)
from backend.service.application.models.yolo_core_common.targets.pose import (
    normalize_gt_keypoints_tensor,
)
from backend.service.application.models.yolo_core_common.targets.segmentation import (
    rasterize_segmentation_polygons,
    select_object_segmentation_polygons,
)

__all__ = [
    "anchor_in_rotated_box",
    "bbox_xyxy_to_distances",
    "decode_distances_to_rboxes",
    "normalize_gt_keypoints_tensor",
    "rasterize_segmentation_polygons",
    "rbox_to_distances",
    "select_object_segmentation_polygons",
    "xywhr_to_corners",
    "xywhr_to_xyxy",
]
