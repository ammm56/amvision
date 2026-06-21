"""YOLO11 classification runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.contracts.classification.prediction import (
    ClassificationPredictionCategory,
    ClassificationPredictionExecutionResult,
    ClassificationPredictionRequest,
    ClassificationRuntimeSessionInfo,
    ClassificationRuntimeTensorSpec,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot


Yolo11ClassificationRuntimeTensorSpec = ClassificationRuntimeTensorSpec
Yolo11ClassificationRuntimeSessionInfo = ClassificationRuntimeSessionInfo
Yolo11ClassificationPredictionRequest = ClassificationPredictionRequest
Yolo11ClassificationPredictionCategory = ClassificationPredictionCategory
Yolo11ClassificationPredictionExecutionResult = ClassificationPredictionExecutionResult


class Yolo11ClassificationPredictionSession(Protocol):
    """定义可重复执行的 YOLO11 classification runtime session 接口。"""

    def predict(
        self,
        request: Yolo11ClassificationPredictionRequest,
    ) -> Yolo11ClassificationPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class Yolo11ClassificationPredictor(Protocol):
    """定义 YOLO11 classification 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: Yolo11ClassificationPredictionRequest,
    ) -> Yolo11ClassificationPredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolo11_classification_top_k(
    *,
    request: Yolo11ClassificationPredictionRequest,
    class_count: int,
) -> int:
    """返回当前请求实际使用的 top-k 值。"""

    if request.top_k <= 0:
        raise InvalidRequestError("top_k 必须大于 0", details={"top_k": request.top_k})
    return min(int(request.top_k), int(class_count))


__all__ = [
    "Yolo11ClassificationPredictionCategory",
    "Yolo11ClassificationPredictionExecutionResult",
    "Yolo11ClassificationPredictionRequest",
    "Yolo11ClassificationPredictionSession",
    "Yolo11ClassificationPredictor",
    "Yolo11ClassificationRuntimeSessionInfo",
    "Yolo11ClassificationRuntimeTensorSpec",
    "resolve_yolo11_classification_top_k",
]
