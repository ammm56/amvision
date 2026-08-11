"""YOLOv8 detection epoch loop 规则工具。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.models.training.metric_policy import (
    resolve_best_metric_decision,
)
from backend.service.application.models.yolo_core_common.training.validation_schedule import (
    should_run_yolo_validation,
)


@dataclass(frozen=True)
class YoloV8DetectionBestMetricUpdate:
    """描述单轮 epoch 后 best metric 是否更新。"""

    improved: bool
    candidate_value: float


def should_run_yolov8_detection_validation(
    *,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
    validation_sample_count: int,
) -> bool:
    """判断当前 epoch 是否需要执行 YOLOv8 detection validation。"""

    return should_run_yolo_validation(
        epoch_index=epoch,
        max_epochs=max_epochs,
        evaluation_interval=evaluation_interval,
        has_validation_samples=validation_sample_count > 0,
    )


def resolve_yolov8_detection_best_metric_name(*, has_validation: bool) -> str:
    """返回 YOLOv8 detection 默认 best metric 名称。"""

    return "map50_95" if has_validation else "train_loss"


def resolve_yolov8_detection_initial_best_metric_value(*, has_validation: bool) -> float:
    """返回 YOLOv8 detection 初始 best metric 值。"""

    return float("-inf") if has_validation else float("inf")


def resolve_yolov8_detection_best_metric_update(
    *,
    has_validation: bool,
    validation_ran: bool,
    current_metric_value: float | None,
    train_loss: float,
    best_metric_value: float,
) -> YoloV8DetectionBestMetricUpdate:
    """比较当前 epoch 指标和历史 best metric。"""

    if has_validation and not validation_ran:
        return YoloV8DetectionBestMetricUpdate(
            improved=False,
            candidate_value=float(best_metric_value),
        )

    decision = resolve_best_metric_decision(
        current_value=current_metric_value if has_validation else train_loss,
        best_value=best_metric_value,
        direction="maximize" if has_validation else "minimize",
        minimum=0.0,
        maximum=1.0 if has_validation else None,
    )
    return YoloV8DetectionBestMetricUpdate(
        improved=decision.improved,
        candidate_value=decision.candidate_value,
    )


def serialize_yolov8_detection_best_metric_value(
    *,
    has_validation: bool,
    best_metric_value: float,
) -> float | None:
    """把内部 best metric 哨兵值转换为对外展示值。"""

    if has_validation and best_metric_value == float("-inf"):
        return None
    if not has_validation and best_metric_value == float("inf"):
        return None
    return round(float(best_metric_value), 6)


__all__ = [
    "YoloV8DetectionBestMetricUpdate",
    "resolve_yolov8_detection_best_metric_name",
    "resolve_yolov8_detection_best_metric_update",
    "resolve_yolov8_detection_initial_best_metric_value",
    "serialize_yolov8_detection_best_metric_value",
    "should_run_yolov8_detection_validation",
]
