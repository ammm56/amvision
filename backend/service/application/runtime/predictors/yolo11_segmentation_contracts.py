"""YOLO11 segmentation runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.application.runtime.segmentation_runtime_contracts import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)


DEFAULT_YOLO11_SEGMENTATION_NMS_THRESHOLD = 0.65

Yolo11SegmentationRuntimeTensorSpec = SegmentationRuntimeTensorSpec
Yolo11SegmentationRuntimeSessionInfo = SegmentationRuntimeSessionInfo
Yolo11SegmentationPredictionRequest = SegmentationPredictionRequest
Yolo11SegmentationPredictionInstance = SegmentationPredictionInstance
Yolo11SegmentationPredictionExecutionResult = SegmentationPredictionExecutionResult


class Yolo11SegmentationPredictionSession(Protocol):
    """定义可重复执行的 YOLO11 segmentation runtime session 接口。"""

    def predict(
        self,
        request: Yolo11SegmentationPredictionRequest,
    ) -> Yolo11SegmentationPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class Yolo11SegmentationPredictor(Protocol):
    """定义 YOLO11 segmentation 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: Yolo11SegmentationPredictionRequest,
    ) -> Yolo11SegmentationPredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolo11_segmentation_probability(
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
    "DEFAULT_YOLO11_SEGMENTATION_NMS_THRESHOLD",
    "Yolo11SegmentationPredictionExecutionResult",
    "Yolo11SegmentationPredictionInstance",
    "Yolo11SegmentationPredictionRequest",
    "Yolo11SegmentationPredictionSession",
    "Yolo11SegmentationPredictor",
    "Yolo11SegmentationRuntimeSessionInfo",
    "Yolo11SegmentationRuntimeTensorSpec",
    "resolve_yolo11_segmentation_probability",
]
