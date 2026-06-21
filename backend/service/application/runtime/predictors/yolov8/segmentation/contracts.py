"""YOLOv8 segmentation runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.application.runtime.contracts.segmentation import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)


DEFAULT_YOLOV8_SEGMENTATION_NMS_THRESHOLD = 0.65

YoloV8SegmentationRuntimeTensorSpec = SegmentationRuntimeTensorSpec
YoloV8SegmentationRuntimeSessionInfo = SegmentationRuntimeSessionInfo
YoloV8SegmentationPredictionRequest = SegmentationPredictionRequest
YoloV8SegmentationPredictionInstance = SegmentationPredictionInstance
YoloV8SegmentationPredictionExecutionResult = SegmentationPredictionExecutionResult


class YoloV8SegmentationPredictionSession(Protocol):
    """定义可重复执行的 YOLOv8 segmentation runtime session 接口。"""

    def predict(
        self,
        request: YoloV8SegmentationPredictionRequest,
    ) -> YoloV8SegmentationPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class YoloV8SegmentationPredictor(Protocol):
    """定义 YOLOv8 segmentation 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: YoloV8SegmentationPredictionRequest,
    ) -> YoloV8SegmentationPredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolov8_segmentation_probability(
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
    "DEFAULT_YOLOV8_SEGMENTATION_NMS_THRESHOLD",
    "YoloV8SegmentationPredictionExecutionResult",
    "YoloV8SegmentationPredictionInstance",
    "YoloV8SegmentationPredictionRequest",
    "YoloV8SegmentationPredictionSession",
    "YoloV8SegmentationPredictor",
    "YoloV8SegmentationRuntimeSessionInfo",
    "YoloV8SegmentationRuntimeTensorSpec",
    "resolve_yolov8_segmentation_probability",
]
