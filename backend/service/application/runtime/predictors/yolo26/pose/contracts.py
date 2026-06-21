"""YOLO26 pose runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.contracts.pose.prediction import (
    PosePredictionExecutionResult,
    PosePredictionInstance,
    PosePredictionKeypoint,
    PosePredictionRequest,
    PoseRuntimeSessionInfo,
    PoseRuntimeTensorSpec,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot


DEFAULT_YOLO26_POSE_NMS_THRESHOLD = 0.65

Yolo26PoseRuntimeTensorSpec = PoseRuntimeTensorSpec
Yolo26PoseRuntimeSessionInfo = PoseRuntimeSessionInfo
Yolo26PosePredictionRequest = PosePredictionRequest
Yolo26PosePredictionKeypoint = PosePredictionKeypoint
Yolo26PosePredictionInstance = PosePredictionInstance
Yolo26PosePredictionExecutionResult = PosePredictionExecutionResult


class Yolo26PosePredictionSession(Protocol):
    """定义可重复执行的 YOLO26 pose runtime session 接口。"""

    def predict(
        self, request: Yolo26PosePredictionRequest
    ) -> Yolo26PosePredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class Yolo26PosePredictor(Protocol):
    """定义 YOLO26 pose 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: Yolo26PosePredictionRequest,
    ) -> Yolo26PosePredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolo26_pose_probability(
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
    "DEFAULT_YOLO26_POSE_NMS_THRESHOLD",
    "Yolo26PosePredictionExecutionResult",
    "Yolo26PosePredictionInstance",
    "Yolo26PosePredictionKeypoint",
    "Yolo26PosePredictionRequest",
    "Yolo26PosePredictionSession",
    "Yolo26PosePredictor",
    "Yolo26PoseRuntimeSessionInfo",
    "Yolo26PoseRuntimeTensorSpec",
    "resolve_yolo26_pose_probability",
]
