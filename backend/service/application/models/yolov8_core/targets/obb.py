"""YOLOv8 OBB target 编码入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.targets.obb import (
    anchor_in_rotated_box,
    decode_distances_to_rboxes,
    rbox_to_distances,
    xywhr_to_corners,
)


def yolov8_anchor_in_rotated_box(
    *,
    torch_module: Any,
    anchor_points: Any,
    corners: Any,
) -> Any:
    """判断 YOLOv8 anchor 是否落在旋转框内。"""

    return anchor_in_rotated_box(
        torch_module=torch_module,
        anchor_points=anchor_points,
        corners=corners,
    )


def yolov8_decode_distances_to_rboxes(
    *,
    torch_module: Any,
    pred_dist: Any,
    pred_angle: Any,
    anchor_points: Any,
) -> Any:
    """把 YOLOv8 OBB distance 与 angle 解码为旋转框。"""

    return decode_distances_to_rboxes(
        torch_module=torch_module,
        pred_dist=pred_dist,
        pred_angle=pred_angle,
        anchor_points=anchor_points,
    )


def yolov8_rbox_to_distances(
    *,
    torch_module: Any,
    rboxes: Any,
    anchor_points: Any,
    stride_tensor: Any,
    reg_max: int,
) -> Any:
    """把 YOLOv8 GT 旋转框编码为距离 target。"""

    return rbox_to_distances(
        torch_module=torch_module,
        rboxes=rboxes,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
        reg_max=reg_max,
    )


def yolov8_xywhr_to_corners(
    *,
    torch_module: Any,
    rboxes: Any,
) -> Any:
    """把 YOLOv8 xywhr 旋转框转换为四角点。"""

    return xywhr_to_corners(torch_module=torch_module, rboxes=rboxes)


__all__ = [
    "yolov8_anchor_in_rotated_box",
    "yolov8_decode_distances_to_rboxes",
    "yolov8_rbox_to_distances",
    "yolov8_xywhr_to_corners",
]
