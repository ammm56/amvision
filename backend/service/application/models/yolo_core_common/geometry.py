"""YOLO 主线共用几何解码工具。"""

from __future__ import annotations

import torch


def make_anchors(
    *,
    feature_maps: tuple[torch.Tensor, ...] | list[torch.Tensor],
    strides: tuple[int, ...],
) -> tuple[torch.Tensor, torch.Tensor]:
    """根据特征图尺寸生成 anchor points 与 stride 张量。"""

    anchor_points: list[torch.Tensor] = []
    stride_values: list[torch.Tensor] = []
    for feature_map, stride in zip(feature_maps, strides, strict=True):
        _, _, height, width = feature_map.shape
        grid_y, grid_x = torch.meshgrid(
            torch.arange(height, device=feature_map.device, dtype=feature_map.dtype),
            torch.arange(width, device=feature_map.device, dtype=feature_map.dtype),
            indexing="ij",
        )
        points = torch.stack((grid_x, grid_y), dim=-1).reshape(-1, 2) + 0.5
        anchor_points.append(points)
        stride_values.append(
            torch.full(
                (height * width, 1),
                float(stride),
                device=feature_map.device,
                dtype=feature_map.dtype,
            )
        )
    return torch.cat(anchor_points, dim=0), torch.cat(stride_values, dim=0)


def dist2bbox_xyxy(
    *,
    distances: torch.Tensor,
    anchor_points: torch.Tensor,
    stride_tensor: torch.Tensor,
) -> torch.Tensor:
    """把 left/top/right/bottom 距离解码成 xyxy 边界框。"""

    left_top, right_bottom = distances.chunk(2, dim=1)
    x1y1 = anchor_points.transpose(1, 2) - left_top
    x2y2 = anchor_points.transpose(1, 2) + right_bottom
    return torch.cat((x1y1, x2y2), dim=1) * stride_tensor.transpose(1, 2)


def dist2rbox(
    pred_dist: torch.Tensor,
    pred_angle: torch.Tensor,
    anchor_points: torch.Tensor,
    dim: int = 1,
) -> torch.Tensor:
    """把距离分布、角度和 anchor points 解码成 xywhr 旋转框。"""

    left_top, right_bottom = pred_dist.split(2, dim=dim)
    cos_angle = torch.cos(pred_angle)
    sin_angle = torch.sin(pred_angle)
    xf, yf = (right_bottom - left_top).chunk(2, dim=dim)
    x = xf * cos_angle - yf * sin_angle
    y = xf * sin_angle + yf * cos_angle
    xy = torch.cat([x, y], dim=dim)
    if anchor_points.ndim == 2:
        xy = xy + anchor_points.unsqueeze(0).permute(0, 2, 1)
    else:
        xy = xy + anchor_points
    return torch.cat([xy, left_top + right_bottom], dim=dim)
