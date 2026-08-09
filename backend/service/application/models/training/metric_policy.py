"""训练指标有效性与最佳 checkpoint 比较规则。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import sys
from typing import Literal


MetricDirection = Literal["maximize", "minimize"]


@dataclass(frozen=True)
class BestMetricDecision:
    """描述当前指标是否严格刷新历史最佳结果。"""

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


def resolve_best_metric_decision(
    *,
    current_value: object,
    best_value: object,
    direction: MetricDirection,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> BestMetricDecision:
    """只允许有效且严格更优的指标替换历史 best checkpoint。"""

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
) -> bool:
    """判断当前指标是否是有效且严格更优的 best 候选。"""

    return resolve_best_metric_decision(
        current_value=current_value,
        best_value=best_value,
        direction=direction,
        minimum=minimum,
        maximum=maximum,
    ).improved


__all__ = [
    "BestMetricDecision",
    "MetricDirection",
    "is_better_training_metric",
    "is_valid_training_metric",
    "resolve_best_metric_decision",
]
