"""YOLO11 OBB target 编码和旋转框几何辅助函数。"""

from __future__ import annotations

from typing import Any


def yolo11_anchor_in_rotated_box(
    *,
    torch_module: Any,
    anchor_points: Any,
    corners: Any,
) -> Any:
    """判断 anchor 是否位于 YOLO11 旋转框内部。"""

    gt_count = int(corners.shape[0])
    anchor_count = int(anchor_points.shape[0])
    if gt_count == 0 or anchor_count == 0:
        return torch_module.zeros(
            gt_count,
            anchor_count,
            dtype=torch_module.bool,
            device=anchor_points.device,
        )

    point_a = corners[:, 0:1, :]
    point_b = corners[:, 1:2, :]
    point_d = corners[:, 3:4, :]
    vector_ab = point_b - point_a
    vector_ad = point_d - point_a
    vector_ap = anchor_points.view(1, -1, 2) - point_a
    norm_ab = (vector_ab * vector_ab).sum(dim=-1).clamp_min(1e-9)
    norm_ad = (vector_ad * vector_ad).sum(dim=-1).clamp_min(1e-9)
    dot_ab = (vector_ap * vector_ab).sum(dim=-1)
    dot_ad = (vector_ap * vector_ad).sum(dim=-1)
    return (dot_ab >= 0) & (dot_ab <= norm_ab) & (dot_ad >= 0) & (dot_ad <= norm_ad)


def yolo11_decode_distances_to_rboxes(
    *,
    torch_module: Any,
    pred_dist: Any,
    pred_angle: Any,
    anchor_points: Any,
) -> Any:
    """把 YOLO11 OBB distance 与 angle 解码为 grid 坐标系 xywhr。"""

    left_top, right_bottom = pred_dist.split(2, dim=-1)
    cos_angle = pred_angle.cos()
    sin_angle = pred_angle.sin()
    x_forward, y_forward = ((right_bottom - left_top) / 2.0).split(1, dim=-1)
    offset_x = x_forward * cos_angle - y_forward * sin_angle
    offset_y = x_forward * sin_angle + y_forward * cos_angle
    center_xy = torch_module.cat([offset_x, offset_y], dim=-1) + anchor_points
    width_height = left_top + right_bottom
    return torch_module.cat([center_xy, width_height, pred_angle], dim=-1)


def yolo11_rbox_to_distances(
    *,
    torch_module: Any,
    rboxes: Any,
    anchor_points: Any,
    stride_tensor: Any,
    reg_max: int,
) -> Any:
    """把像素坐标系 YOLO11 GT 旋转框编码为 DFL 使用的 ltrb 距离。"""

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


def yolo11_scale_rbox_to_grid(
    *,
    rboxes: Any,
    stride_tensor: Any,
) -> Any:
    """把像素坐标系 xywhr 旋转框转成 grid 坐标系。"""

    stride = stride_tensor.view(-1, 1).clamp_min(1e-6)
    scaled = rboxes.clone()
    scaled[:, :4] = scaled[:, :4] / stride
    return scaled


def yolo11_xywhr_to_corners(
    *,
    torch_module: Any,
    rboxes: Any,
) -> Any:
    """把 YOLO11 xywhr 旋转框转换为四角点。"""

    center_x, center_y, width, height, angle = rboxes.unbind(dim=-1)
    cos_angle = angle.cos()
    sin_angle = angle.sin()
    half_width = width / 2.0
    half_height = height / 2.0

    dx = torch_module.stack([-half_width, half_width, half_width, -half_width], dim=-1)
    dy = torch_module.stack(
        [-half_height, -half_height, half_height, half_height], dim=-1
    )
    rotated_x = dx * cos_angle.unsqueeze(-1) - dy * sin_angle.unsqueeze(-1)
    rotated_y = dx * sin_angle.unsqueeze(-1) + dy * cos_angle.unsqueeze(-1)
    corners_x = rotated_x + center_x.unsqueeze(-1)
    corners_y = rotated_y + center_y.unsqueeze(-1)
    return torch_module.stack([corners_x, corners_y], dim=-1)


def yolo11_xywhr_to_xyxy(torch_module: Any, rboxes: Any) -> Any:
    """把 YOLO11 xywhr 旋转框转成轴对齐 xyxy 包围盒。"""

    corners = yolo11_xywhr_to_corners(
        torch_module=torch_module,
        rboxes=rboxes.reshape(-1, 5),
    )
    min_xy = corners.min(dim=1).values
    max_xy = corners.max(dim=1).values
    return torch_module.cat([min_xy, max_xy], dim=-1).view(*rboxes.shape[:-1], 4)


__all__ = [
    "yolo11_anchor_in_rotated_box",
    "yolo11_decode_distances_to_rboxes",
    "yolo11_rbox_to_distances",
    "yolo11_scale_rbox_to_grid",
    "yolo11_xywhr_to_corners",
    "yolo11_xywhr_to_xyxy",
]
