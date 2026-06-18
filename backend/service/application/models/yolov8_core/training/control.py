"""YOLOv8 detection epoch 控制规则。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YoloV8DetectionEpochControlDecision:
    """描述 YOLOv8 detection 在 epoch 边界需要执行的控制动作。"""

    save_checkpoint: bool
    pause_training: bool
    terminate_training: bool


def resolve_yolov8_detection_epoch_control(
    *,
    save_checkpoint_requested: bool,
    pause_training_requested: bool,
    terminate_training_requested: bool,
) -> YoloV8DetectionEpochControlDecision:
    """把应用层控制请求转换成 YOLOv8 detection 训练循环动作。"""

    pause_training = bool(pause_training_requested)
    terminate_training = bool(terminate_training_requested)
    save_checkpoint = bool(save_checkpoint_requested) or pause_training
    return YoloV8DetectionEpochControlDecision(
        save_checkpoint=save_checkpoint,
        pause_training=pause_training,
        terminate_training=terminate_training,
    )


__all__ = [
    "YoloV8DetectionEpochControlDecision",
    "resolve_yolov8_detection_epoch_control",
]
