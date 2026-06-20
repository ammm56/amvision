"""YOLO26 detection epoch loop 规则工具。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Yolo26DetectionBestMetricUpdate:
    """描述单轮 epoch 后 best metric 是否更新。"""

    improved: bool
    candidate_value: float


def should_run_yolo26_detection_validation(
    *,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
    validation_sample_count: int,
) -> bool:
    """判断当前 epoch 是否需要执行 YOLO26 detection validation。"""

    if validation_sample_count <= 0:
        return False
    resolved_interval = max(1, int(evaluation_interval))
    return int(epoch) == int(max_epochs) or int(epoch) % resolved_interval == 0


def resolve_yolo26_detection_best_metric_name(*, has_validation: bool) -> str:
    """返回 YOLO26 detection 默认 best metric 名称。"""

    return "map50_95" if has_validation else "train_loss"


def resolve_yolo26_detection_initial_best_metric_value(
    *, has_validation: bool
) -> float:
    """返回 YOLO26 detection 初始 best metric 值。"""

    return float("-inf") if has_validation else float("inf")


def resolve_yolo26_detection_best_metric_update(
    *,
    validation_ran: bool,
    current_metric_value: float | None,
    train_loss: float,
    best_metric_value: float,
) -> Yolo26DetectionBestMetricUpdate:
    """比较当前 epoch 指标和历史 best metric。"""

    if validation_ran and current_metric_value is not None:
        if current_metric_value >= best_metric_value:
            return Yolo26DetectionBestMetricUpdate(
                improved=True,
                candidate_value=current_metric_value,
            )
        return Yolo26DetectionBestMetricUpdate(
            improved=False,
            candidate_value=best_metric_value,
        )
    if train_loss <= best_metric_value:
        return Yolo26DetectionBestMetricUpdate(
            improved=True,
            candidate_value=train_loss,
        )
    return Yolo26DetectionBestMetricUpdate(
        improved=False,
        candidate_value=best_metric_value,
    )


def serialize_yolo26_detection_best_metric_value(
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
    "Yolo26DetectionBestMetricUpdate",
    "resolve_yolo26_detection_best_metric_name",
    "resolve_yolo26_detection_best_metric_update",
    "resolve_yolo26_detection_initial_best_metric_value",
    "serialize_yolo26_detection_best_metric_value",
    "should_run_yolo26_detection_validation",
]
