"""YOLOv8 pose runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.pose_runtime_contracts import (
    PosePredictionExecutionResult,
    PosePredictionInstance,
    PosePredictionKeypoint,
    PosePredictionRequest,
    PoseRuntimeSessionInfo,
    PoseRuntimeTensorSpec,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot


DEFAULT_YOLOV8_POSE_NMS_THRESHOLD = 0.65

YoloV8PoseRuntimeTensorSpec = PoseRuntimeTensorSpec
YoloV8PoseRuntimeSessionInfo = PoseRuntimeSessionInfo
YoloV8PosePredictionRequest = PosePredictionRequest
YoloV8PosePredictionKeypoint = PosePredictionKeypoint
YoloV8PosePredictionInstance = PosePredictionInstance
YoloV8PosePredictionExecutionResult = PosePredictionExecutionResult


class YoloV8PosePredictionSession(Protocol):
    """定义可重复执行的 YOLOv8 pose runtime session 接口。"""

    def predict(self, request: YoloV8PosePredictionRequest) -> YoloV8PosePredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class YoloV8PosePredictor(Protocol):
    """定义 YOLOv8 pose 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: YoloV8PosePredictionRequest,
    ) -> YoloV8PosePredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolov8_pose_probability(
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
    "DEFAULT_YOLOV8_POSE_NMS_THRESHOLD",
    "YoloV8PosePredictionExecutionResult",
    "YoloV8PosePredictionInstance",
    "YoloV8PosePredictionKeypoint",
    "YoloV8PosePredictionRequest",
    "YoloV8PosePredictionSession",
    "YoloV8PosePredictor",
    "YoloV8PoseRuntimeSessionInfo",
    "YoloV8PoseRuntimeTensorSpec",
    "resolve_yolov8_pose_probability",
]
