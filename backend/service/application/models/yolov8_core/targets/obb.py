"""YOLOv8 OBB target 编码入口。"""

from __future__ import annotations

from typing import Any


def yolov8_anchor_in_rotated_box(
    *,
    torch_module: Any,
    anchor_points: Any,
    corners: Any,
) -> Any:
    """判断 YOLOv8 anchor 是否位于旋转框轴对齐包围范围内。"""

    num_gt = int(corners.shape[0])
    num_anchors = int(anchor_points.shape[0])
    if num_gt == 0 or num_anchors == 0:
        return torch_module.zeros(
            num_gt,
            num_anchors,
            dtype=torch_module.bool,
            device=anchor_points.device,
        )

    min_xy = corners.min(dim=1).values
    max_xy = corners.max(dim=1).values
    anchor_x = anchor_points[:, 0].unsqueeze(0)
    anchor_y = anchor_points[:, 1].unsqueeze(0)
    return (
        (anchor_x >= min_xy[:, 0:1])
        & (anchor_x <= max_xy[:, 0:1])
        & (anchor_y >= min_xy[:, 1:2])
        & (anchor_y <= max_xy[:, 1:2])
    )


def yolov8_decode_distances_to_rboxes(
    *,
    torch_module: Any,
    pred_dist: Any,
    pred_angle: Any,
    anchor_points: Any,
) -> Any:
    """把 YOLOv8 OBB distance 与 angle 解码为 xywhr 旋转框。"""

    left_top, right_bottom = pred_dist.chunk(2, dim=-1)
    cos_angle = pred_angle.cos()
    sin_angle = pred_angle.sin()
    x_forward, y_forward = (right_bottom - left_top).chunk(2, dim=-1)
    x = x_forward * cos_angle - y_forward * sin_angle
    y = x_forward * sin_angle + y_forward * cos_angle
    xy = torch_module.cat([x, y], dim=-1) + anchor_points
    wh = left_top + right_bottom
    return torch_module.cat([xy, wh, pred_angle], dim=-1)


def yolov8_rbox_to_distances(
    *,
    torch_module: Any,
    rboxes: Any,
    anchor_points: Any,
    stride_tensor: Any,
    reg_max: int,
) -> Any:
    """把 YOLOv8 GT 旋转框编码为 DFL 使用的 ltrb 距离 target。"""

    stride = stride_tensor.view(-1, 1).clamp_min(1e-6)
    xy = rboxes[:, :2]
    wh = rboxes[:, 2:4]
    angle = rboxes[:, 4:5]

    offset = xy - anchor_points * stride
    cos_angle = angle.cos()
    sin_angle = angle.sin()
    dx = offset[:, 0:1] * cos_angle + offset[:, 1:2] * sin_angle
    dy = -offset[:, 0:1] * sin_angle + offset[:, 1:2] * cos_angle

    half_width = wh[:, 0:1] / 2.0
    half_height = wh[:, 1:2] / 2.0
    left = (half_width - dx) / stride
    top = (half_height - dy) / stride
    right = (half_width + dx) / stride
    bottom = (half_height + dy) / stride

    distances = torch_module.cat([left, top, right, bottom], dim=-1).clamp_min(0.0)
    if reg_max > 1:
        distances = distances.clamp(max=float(reg_max) - 1.0001)
    return distances


def yolov8_xywhr_to_corners(
    *,
    torch_module: Any,
    rboxes: Any,
) -> Any:
    """把 YOLOv8 xywhr 旋转框转换为四角点。"""

    center_x, center_y, width, height, angle = rboxes.unbind(dim=-1)
    cos_angle = angle.cos()
    sin_angle = angle.sin()
    half_width = width / 2.0
    half_height = height / 2.0

    dx = torch_module.stack([-half_width, half_width, half_width, -half_width], dim=-1)
    dy = torch_module.stack([-half_height, -half_height, half_height, half_height], dim=-1)
    rotated_x = dx * cos_angle.unsqueeze(-1) - dy * sin_angle.unsqueeze(-1)
    rotated_y = dx * sin_angle.unsqueeze(-1) + dy * cos_angle.unsqueeze(-1)
    corners_x = rotated_x + center_x.unsqueeze(-1)
    corners_y = rotated_y + center_y.unsqueeze(-1)
    return torch_module.stack([corners_x, corners_y], dim=-1)


def yolov8_xywhr_to_xyxy(torch_module: Any, rboxes: Any) -> Any:
    """把 YOLOv8 xywhr 旋转框转为轴对齐 xyxy 包围盒。"""

    corners = yolov8_xywhr_to_corners(
        torch_module=torch_module,
        rboxes=rboxes.reshape(-1, 5),
    )
    min_xy = corners.min(dim=1).values
    max_xy = corners.max(dim=1).values
    return torch_module.cat([min_xy, max_xy], dim=-1).view(*rboxes.shape[:-1], 4)


__all__ = [
    "yolov8_anchor_in_rotated_box",
    "yolov8_decode_distances_to_rboxes",
    "yolov8_rbox_to_distances",
    "yolov8_xywhr_to_corners",
    "yolov8_xywhr_to_xyxy",
]
