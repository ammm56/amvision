"""YOLO26 detection target 编码。"""

from __future__ import annotations

from typing import Any


def yolo26_bbox_xyxy_to_distances(
    *,
    torch_module: Any,
    boxes_xyxy: Any,
    anchor_points: Any,
    stride_tensor: Any,
    reg_max: int,
) -> Any:
    """把正样本 gt bbox 转成 YOLO26 DFL 或 LTRB 回归目标。"""

    stride = stride_tensor.view(-1, 1).clamp_min(1e-6)
    scaled_boxes = boxes_xyxy / stride.repeat(1, 4)
    left = anchor_points[:, 0] - scaled_boxes[:, 0]
    top = anchor_points[:, 1] - scaled_boxes[:, 1]
    right = scaled_boxes[:, 2] - anchor_points[:, 0]
    bottom = scaled_boxes[:, 3] - anchor_points[:, 1]
    distances = torch_module.stack((left, top, right, bottom), dim=1).clamp_min(0.0)
    if reg_max > 1:
        return distances.clamp(max=float(reg_max) - 1.0001)
    return distances
