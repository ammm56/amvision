"""YOLOv8 detection 训练 dataloader 计划。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class YoloV8DetectionTrainingDataloaderPlan:
    """描述 YOLOv8 detection 训练 dataloader 的批次数和 iteration 边界。"""

    train_sample_count: int
    batch_size: int
    max_epochs: int
    resume_epoch: int
    batches_per_epoch: int
    total_iterations: int
    initial_global_iteration: int


def plan_yolov8_detection_training_dataloader(
    *,
    train_sample_count: int,
    batch_size: int,
    max_epochs: int,
    resume_epoch: int,
) -> YoloV8DetectionTrainingDataloaderPlan:
    """计算 YOLOv8 detection 训练 dataloader 的执行边界。"""

    resolved_train_sample_count = int(train_sample_count)
    if resolved_train_sample_count <= 0:
        raise InvalidRequestError("YOLOv8 detection 训练 split 不包含可用样本")
    resolved_batch_size = max(1, int(batch_size))
    resolved_max_epochs = max(1, int(max_epochs))
    resolved_resume_epoch = max(0, int(resume_epoch))
    if resolved_resume_epoch >= resolved_max_epochs:
        raise InvalidRequestError(
            "YOLOv8 detection resume checkpoint 已经达到或超过本次训练请求的最大 epoch",
            details={
                "resume_epoch": resolved_resume_epoch,
                "max_epochs": resolved_max_epochs,
            },
        )

    batches_per_epoch = max(
        1,
        (resolved_train_sample_count + resolved_batch_size - 1) // resolved_batch_size,
    )
    return YoloV8DetectionTrainingDataloaderPlan(
        train_sample_count=resolved_train_sample_count,
        batch_size=resolved_batch_size,
        max_epochs=resolved_max_epochs,
        resume_epoch=resolved_resume_epoch,
        batches_per_epoch=batches_per_epoch,
        total_iterations=resolved_max_epochs * batches_per_epoch,
        initial_global_iteration=resolved_resume_epoch * batches_per_epoch,
    )


__all__ = [
    "YoloV8DetectionTrainingDataloaderPlan",
    "plan_yolov8_detection_training_dataloader",
]
