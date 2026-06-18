"""YOLOv8 detection decode。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.decode import (
    decode_detection_training_predictions,
)


def decode_yolov8_detection_training_predictions(
    *,
    torch_module: Any,
    detect_head: Any,
    raw_outputs: dict[str, Any],
) -> dict[str, Any]:
    """把 YOLOv8 detection 训练态 raw outputs 解码为 loss 输入。"""

    return decode_detection_training_predictions(
        torch_module=torch_module,
        detect_head=detect_head,
        raw_outputs=raw_outputs,
    )


__all__ = ["decode_yolov8_detection_training_predictions"]
