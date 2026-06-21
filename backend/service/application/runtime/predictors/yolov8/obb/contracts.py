"""YOLOv8 OBB runtime 类型和参数校验。"""

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
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot


DEFAULT_YOLOV8_OBB_NMS_THRESHOLD = 0.65

YoloV8ObbRuntimeTensorSpec = ObbRuntimeTensorSpec
YoloV8ObbRuntimeSessionInfo = ObbRuntimeSessionInfo
YoloV8ObbPredictionRequest = ObbPredictionRequest
YoloV8ObbPredictionInstance = ObbPredictionInstance
YoloV8ObbPredictionExecutionResult = ObbPredictionExecutionResult


class YoloV8ObbPredictionSession(Protocol):
    """定义可重复执行的 YOLOv8 OBB runtime session 接口。"""

    def predict(self, request: YoloV8ObbPredictionRequest) -> YoloV8ObbPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class YoloV8ObbPredictor(Protocol):
    """定义 YOLOv8 OBB 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: YoloV8ObbPredictionRequest,
    ) -> YoloV8ObbPredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolov8_obb_probability(
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
    "DEFAULT_YOLOV8_OBB_NMS_THRESHOLD",
    "YoloV8ObbPredictionExecutionResult",
    "YoloV8ObbPredictionInstance",
    "YoloV8ObbPredictionRequest",
    "YoloV8ObbPredictionSession",
    "YoloV8ObbPredictor",
    "YoloV8ObbRuntimeSessionInfo",
    "YoloV8ObbRuntimeTensorSpec",
    "resolve_yolov8_obb_probability",
]
