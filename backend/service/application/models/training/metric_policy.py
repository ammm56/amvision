"""训练指标有效性与最佳 checkpoint 比较规则。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import sys
from typing import Literal


MetricDirection = Literal["maximize", "minimize"]


@dataclass(frozen=True)
class BestMetricDecision:
    """描述当前指标是否应替换历史最佳结果。"""

    improved: bool
    candidate_value: float


def is_valid_training_metric(
    value: object,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> bool:
    """判断指标是否是位于业务范围内的有限实数。"""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    resolved_value = float(value)
    if not math.isfinite(resolved_value) or resolved_value < minimum:
        return False
    return maximum is None or resolved_value <= maximum


def serialize_training_metric(
    value: object,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float | None:
    """把内部指标状态转换为公开 API/文件可用的有限数值。

    训练器可以用负数或无穷值表示“尚未评估”，但这些内部状态不能泄漏到
    task progress、metrics JSON 或前端，也不能被误解为真实模型指标。
    """

    if not is_valid_training_metric(
        value,
        minimum=minimum,
        maximum=maximum,
    ):
        return None
    return float(value)


def resolve_best_metric_decision(
    *,
    current_value: object,
    best_value: object,
    direction: MetricDirection,
    minimum: float = 0.0,
    maximum: float | None = None,
    prefer_latest_on_tie: bool = False,
) -> BestMetricDecision:
    """选择有效的最佳指标，并按调用方策略处理并列。"""

    if direction not in {"maximize", "minimize"}:
        raise ValueError(f"不支持的训练指标方向: {direction}")

    if not is_valid_training_metric(
        current_value,
        minimum=minimum,
        maximum=maximum,
    ):
        best_is_valid = is_valid_training_metric(
            best_value,
            minimum=minimum,
            maximum=maximum,
        )
        if best_is_valid:
            fallback_value = float(best_value)
        elif direction == "maximize":
            fallback_value = float(minimum)
        else:
            fallback_value = (
                float(maximum) if maximum is not None else sys.float_info.max
            )
        return BestMetricDecision(improved=False, candidate_value=fallback_value)
    resolved_current = float(current_value)
    best_is_valid = is_valid_training_metric(
        best_value,
        minimum=minimum,
        maximum=maximum,
    )
    if direction == "maximize":
        improved = not best_is_valid or resolved_current > float(best_value)
    elif direction == "minimize":
        improved = not best_is_valid or resolved_current < float(best_value)
    if best_is_valid and prefer_latest_on_tie and resolved_current == float(best_value):
        improved = True
    return BestMetricDecision(
        improved=improved,
        candidate_value=resolved_current if improved else float(best_value),
    )


def is_better_training_metric(
    *,
    current_value: object,
    best_value: object,
    direction: MetricDirection,
    minimum: float = 0.0,
    maximum: float | None = None,
    prefer_latest_on_tie: bool = False,
) -> bool:
    """判断当前轮的指标是否应成为 best。"""

    return resolve_best_metric_decision(
        current_value=current_value,
        best_value=best_value,
        direction=direction,
        minimum=minimum,
        maximum=maximum,
        prefer_latest_on_tie=prefer_latest_on_tie,
    ).improved


__all__ = [
    "BestMetricDecision",
    "MetricDirection",
    "is_better_training_metric",
    "is_valid_training_metric",
    "resolve_best_metric_decision",
    "serialize_training_metric",
]
