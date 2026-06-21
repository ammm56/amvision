"""YOLOX runtime session 共享类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.contracts.detection import (
    DetectionPredictionDetection,
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot


DEFAULT_YOLOX_NMS_THRESHOLD = 0.65

RuntimeTensorSpec = DetectionRuntimeTensorSpec
YoloXRuntimeSessionInfo = DetectionRuntimeSessionInfo
YoloXPredictionRequest = DetectionPredictionRequest
YoloXPredictionDetection = DetectionPredictionDetection
YoloXPredictionExecutionResult = DetectionPredictionExecutionResult


class YoloXPredictor(Protocol):
    """定义 YOLOX 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: YoloXPredictionRequest,
    ) -> YoloXPredictionExecutionResult:
        """执行一次单图预测。

        参数：
        - runtime_target：运行时快照。
        - request：预测请求。

        返回：
        - YoloXPredictionExecutionResult：预测执行结果。
        """


class YoloXPredictionSession(Protocol):
    """定义可重复执行的 YOLOX runtime session 接口。"""

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。

        参数：
        - request：预测请求。

        返回：
        - YoloXPredictionExecutionResult：预测执行结果。
        """


def resolve_yolox_probability(*, value: object, field_name: str, default: float) -> float:
    """解析并校验概率型浮点值。"""

    resolved_value = float(value) if isinstance(value, int | float) else default
    if resolved_value < 0 or resolved_value > 1:
        raise InvalidRequestError(
            f"{field_name} 必须位于 0 到 1 之间",
            details={field_name: resolved_value},
        )
    return resolved_value
