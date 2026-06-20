"""YOLO11 OBB runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.contracts.obb import (
    ObbPredictionExecutionResult,
    ObbPredictionInstance,
    ObbPredictionRequest,
    ObbRuntimeSessionInfo,
    ObbRuntimeTensorSpec,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot


DEFAULT_YOLO11_OBB_NMS_THRESHOLD = 0.65

Yolo11ObbRuntimeTensorSpec = ObbRuntimeTensorSpec
Yolo11ObbRuntimeSessionInfo = ObbRuntimeSessionInfo
Yolo11ObbPredictionRequest = ObbPredictionRequest
Yolo11ObbPredictionInstance = ObbPredictionInstance
Yolo11ObbPredictionExecutionResult = ObbPredictionExecutionResult


class Yolo11ObbPredictionSession(Protocol):
    """定义可重复执行的 YOLO11 OBB runtime session 接口。"""

    def predict(
        self, request: Yolo11ObbPredictionRequest
    ) -> Yolo11ObbPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class Yolo11ObbPredictor(Protocol):
    """定义 YOLO11 OBB 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: Yolo11ObbPredictionRequest,
    ) -> Yolo11ObbPredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolo11_obb_probability(
    *,
    value: object,
    field_name: str,
    default: float,
) -> float:
    """解析概率型浮点值，并限制在 0 到 1 之间。"""

    resolved_value = float(value) if isinstance(value, int | float) else default
    if resolved_value < 0 or resolved_value > 1:
        raise InvalidRequestError(
            f"{field_name} 必须位于 0 到 1 之间",
            details={field_name: resolved_value},
        )
    return resolved_value


__all__ = [
    "DEFAULT_YOLO11_OBB_NMS_THRESHOLD",
    "Yolo11ObbPredictionExecutionResult",
    "Yolo11ObbPredictionInstance",
    "Yolo11ObbPredictionRequest",
    "Yolo11ObbPredictionSession",
    "Yolo11ObbPredictor",
    "Yolo11ObbRuntimeSessionInfo",
    "Yolo11ObbRuntimeTensorSpec",
    "resolve_yolo11_obb_probability",
]
