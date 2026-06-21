"""YOLO26 segmentation runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)


DEFAULT_YOLO26_SEGMENTATION_NMS_THRESHOLD = 0.65

Yolo26SegmentationRuntimeTensorSpec = SegmentationRuntimeTensorSpec
Yolo26SegmentationRuntimeSessionInfo = SegmentationRuntimeSessionInfo
Yolo26SegmentationPredictionRequest = SegmentationPredictionRequest
Yolo26SegmentationPredictionInstance = SegmentationPredictionInstance
Yolo26SegmentationPredictionExecutionResult = SegmentationPredictionExecutionResult


class Yolo26SegmentationPredictionSession(Protocol):
    """定义可重复执行的 YOLO26 segmentation runtime session 接口。"""

    def predict(
        self,
        request: Yolo26SegmentationPredictionRequest,
    ) -> Yolo26SegmentationPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class Yolo26SegmentationPredictor(Protocol):
    """定义 YOLO26 segmentation 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: Yolo26SegmentationPredictionRequest,
    ) -> Yolo26SegmentationPredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolo26_segmentation_probability(
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
    "DEFAULT_YOLO26_SEGMENTATION_NMS_THRESHOLD",
    "Yolo26SegmentationPredictionExecutionResult",
    "Yolo26SegmentationPredictionInstance",
    "Yolo26SegmentationPredictionRequest",
    "Yolo26SegmentationPredictionSession",
    "Yolo26SegmentationPredictor",
    "Yolo26SegmentationRuntimeSessionInfo",
    "Yolo26SegmentationRuntimeTensorSpec",
    "resolve_yolo26_segmentation_probability",
]
