"""YOLOv8 detection runtime 类型和参数校验。"""

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
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot


DEFAULT_YOLOV8_DETECTION_NMS_THRESHOLD = 0.65

YoloV8DetectionRuntimeTensorSpec = DetectionRuntimeTensorSpec
YoloV8DetectionRuntimeSessionInfo = DetectionRuntimeSessionInfo
YoloV8DetectionPredictionRequest = DetectionPredictionRequest
YoloV8DetectionPredictionDetection = DetectionPredictionDetection
YoloV8DetectionPredictionExecutionResult = DetectionPredictionExecutionResult


class YoloV8DetectionPredictionSession(Protocol):
    """定义可重复执行的 YOLOv8 detection runtime session 接口。"""

    def predict(
        self,
        request: YoloV8DetectionPredictionRequest,
    ) -> YoloV8DetectionPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class YoloV8DetectionPredictor(Protocol):
    """定义 YOLOv8 detection 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: YoloV8DetectionPredictionRequest,
    ) -> YoloV8DetectionPredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolov8_detection_probability(
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
    "DEFAULT_YOLOV8_DETECTION_NMS_THRESHOLD",
    "YoloV8DetectionPredictionDetection",
    "YoloV8DetectionPredictionExecutionResult",
    "YoloV8DetectionPredictionRequest",
    "YoloV8DetectionPredictionSession",
    "YoloV8DetectionPredictor",
    "YoloV8DetectionRuntimeSessionInfo",
    "YoloV8DetectionRuntimeTensorSpec",
    "resolve_yolov8_detection_probability",
]
