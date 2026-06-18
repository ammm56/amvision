"""YOLOv8 pose decode。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.geometry import (
    make_anchors,
)


def decode_yolov8_pose_keypoints(
    *,
    raw_outputs: dict[str, Any],
    strides: tuple[int, ...],
    keypoint_shape: tuple[int, int],
) -> Any:
    """把 YOLOv8 pose 关键点分支输出解码为绝对坐标。"""

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
    decoded[:, :, 0, :] = ((decoded[:, :, 0, :] * 2.0) + anchor_x - 0.5) * stride
    decoded[:, :, 1, :] = ((decoded[:, :, 1, :] * 2.0) + anchor_y - 0.5) * stride
    if keypoint_dimensions > 2:
        decoded[:, :, 2:, :] = decoded[:, :, 2:, :].sigmoid()
    return decoded.view(batch_size, keypoint_count * keypoint_dimensions, -1)


def decode_yolov8_pose_keypoints_xy(
    *,
    pred_xy: Any,
    anchors_xy: Any,
    strides: Any,
) -> Any:
    """把 YOLOv8 pose 训练分支的关键点偏移解码为输入图坐标。"""

    return anchors_xy.unsqueeze(1) + pred_xy * strides.unsqueeze(1) * 2.0


__all__ = [
    "decode_yolov8_pose_keypoints",
    "decode_yolov8_pose_keypoints_xy",
]
