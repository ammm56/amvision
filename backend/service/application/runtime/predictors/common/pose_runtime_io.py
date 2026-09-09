"""Pose 运行时共享 LetterBox；评估显式选择 scaleup，普通推理保持放大。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
    letterbox_yolo_image,
)


def preprocess_pose_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
    scaleup: bool = True,
) -> tuple[Any, YoloLetterboxTransform]:
    """构建 RGB CHW float32 张量，保留变换信息供指标或展示还原。"""
    letterboxed, transform = letterbox_yolo_image(
        cv2_module=cv2_module,
        np_module=np_module,
        image=image,
        input_size=input_size,
        scaleup=scaleup,
    )
    tensor = (
        letterboxed[:, :, ::-1].transpose(2, 0, 1).astype(np_module.float32) / 255.0
    )
    return np_module.ascontiguousarray(tensor, dtype=np_module.float32), transform
