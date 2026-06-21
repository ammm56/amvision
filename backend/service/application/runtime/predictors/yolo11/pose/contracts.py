"""YOLO11 pose runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.contracts.pose import (
    PosePredictionExecutionResult,
    PosePredictionInstance,
    PosePredictionKeypoint,
    PosePredictionRequest,
    PoseRuntimeSessionInfo,
    PoseRuntimeTensorSpec,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot


DEFAULT_YOLO11_POSE_NMS_THRESHOLD = 0.65

Yolo11PoseRuntimeTensorSpec = PoseRuntimeTensorSpec
Yolo11PoseRuntimeSessionInfo = PoseRuntimeSessionInfo
Yolo11PosePredictionRequest = PosePredictionRequest
Yolo11PosePredictionKeypoint = PosePredictionKeypoint
Yolo11PosePredictionInstance = PosePredictionInstance
Yolo11PosePredictionExecutionResult = PosePredictionExecutionResult


class Yolo11PosePredictionSession(Protocol):
    """定义可重复执行的 YOLO11 pose runtime session 接口。"""

    def predict(
        self, request: Yolo11PosePredictionRequest
    ) -> Yolo11PosePredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class Yolo11PosePredictor(Protocol):
    """定义 YOLO11 pose 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: Yolo11PosePredictionRequest,
    ) -> Yolo11PosePredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolo11_pose_probability(
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
    "DEFAULT_YOLO11_POSE_NMS_THRESHOLD",
    "Yolo11PosePredictionExecutionResult",
    "Yolo11PosePredictionInstance",
    "Yolo11PosePredictionKeypoint",
    "Yolo11PosePredictionRequest",
    "Yolo11PosePredictionSession",
    "Yolo11PosePredictor",
    "Yolo11PoseRuntimeSessionInfo",
    "Yolo11PoseRuntimeTensorSpec",
    "resolve_yolo11_pose_probability",
]
