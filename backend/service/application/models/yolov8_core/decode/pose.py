"""YOLOv8 pose decode。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.decode import (
    decode_pose_keypoints,
)


def decode_yolov8_pose_keypoints(
    *,
    raw_outputs: dict[str, Any],
    strides: tuple[int, ...],
    keypoint_shape: tuple[int, int],
) -> Any:
    """把 YOLOv8 pose 关键点分支输出解码为绝对坐标。"""

    return decode_pose_keypoints(
        raw_outputs=raw_outputs,
        strides=strides,
        keypoint_shape=keypoint_shape,
        offset_multiplier=2.0,
        anchor_offset=-0.5,
    )


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
