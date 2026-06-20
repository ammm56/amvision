"""YOLO11 detection 训练执行计划。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo11_core.training.epoch import (
    resolve_yolo11_detection_best_metric_name,
    resolve_yolo11_detection_initial_best_metric_value,
)


@dataclass(frozen=True)
class Yolo11DetectionTrainingExecutionPlan:
    """描述 YOLO11 detection 训练循环的执行边界。"""

    has_validation: bool
    best_metric_name: str
    best_metric_value: float
    total_iterations: int
    initial_global_iteration: int


def plan_yolo11_detection_training_execution(
    *,
    train_sample_count: int,
    validation_sample_count: int,
    batch_size: int,
    max_epochs: int,
    resume_epoch: int,
    resume_best_metric_name: str | None = None,
    resume_best_metric_value: float | None = None,
) -> Yolo11DetectionTrainingExecutionPlan:
    """根据样本数量和 resume 状态返回 YOLO11 detection 训练执行计划。"""

    resolved_batch_size = max(1, int(batch_size))
    iterations_per_epoch = max(
        1, (int(train_sample_count) + resolved_batch_size - 1) // resolved_batch_size
    )
    if resume_epoch >= max_epochs:
        raise InvalidRequestError(
            "resume checkpoint 已经达到或超过本次训练请求的最大 epoch",
            details={"resume_epoch": resume_epoch, "max_epochs": max_epochs},
        )
    has_validation = validation_sample_count > 0
    best_metric_name = (
        resume_best_metric_name.strip()
        if isinstance(resume_best_metric_name, str) and resume_best_metric_name.strip()
        else resolve_yolo11_detection_best_metric_name(has_validation=has_validation)
    )
    best_metric_value = (
        float(resume_best_metric_value)
        if resume_best_metric_value is not None
        else resolve_yolo11_detection_initial_best_metric_value(
            has_validation=has_validation
        )
    )
    return Yolo11DetectionTrainingExecutionPlan(
        has_validation=has_validation,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        total_iterations=max_epochs * iterations_per_epoch,
        initial_global_iteration=resume_epoch * iterations_per_epoch,
    )


__all__ = [
    "Yolo11DetectionTrainingExecutionPlan",
    "plan_yolo11_detection_training_execution",
]
