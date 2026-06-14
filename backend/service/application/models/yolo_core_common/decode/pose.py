"""YOLO 主线 pose decode 边界。"""

from __future__ import annotations

import torch

from backend.service.application.models.yolo_core_common.geometry import make_anchors


def decode_pose_keypoints(
    *,
    raw_outputs: dict[str, torch.Tensor],
    strides: tuple[int, ...],
    keypoint_shape: tuple[int, int],
    offset_multiplier: float,
    anchor_offset: float,
) -> torch.Tensor:
    """把关键点分支输出解码成绝对坐标。"""

    anchor_points, stride_tensor = make_anchors(
        feature_maps=raw_outputs["feats"],
        strides=strides,
    )
    keypoints = raw_outputs["kpts"]
    batch_size = int(keypoints.shape[0])
    keypoint_count = int(keypoint_shape[0])
    keypoint_dimensions = int(keypoint_shape[1])
    decoded = keypoints.view(
        batch_size,
        keypoint_count,
        keypoint_dimensions,
        -1,
    ).clone()
    anchor_x = anchor_points[:, 0].view(1, 1, -1)
    anchor_y = anchor_points[:, 1].view(1, 1, -1)
    stride = stride_tensor.view(1, 1, -1)
    decoded[:, :, 0, :] = (
        (decoded[:, :, 0, :] * float(offset_multiplier)) + anchor_x + float(anchor_offset)
    ) * stride
    decoded[:, :, 1, :] = (
        (decoded[:, :, 1, :] * float(offset_multiplier)) + anchor_y + float(anchor_offset)
    ) * stride
    if keypoint_dimensions > 2:
        decoded[:, :, 2:, :] = decoded[:, :, 2:, :].sigmoid()
    return decoded.view(batch_size, keypoint_count * keypoint_dimensions, -1)
