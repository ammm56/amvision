"""YOLOv8 classification runtime 类型和参数校验。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.contracts.classification import (
    ClassificationPredictionCategory,
    ClassificationPredictionExecutionResult,
    ClassificationPredictionRequest,
    ClassificationRuntimeSessionInfo,
    ClassificationRuntimeTensorSpec,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot


YoloV8ClassificationRuntimeTensorSpec = ClassificationRuntimeTensorSpec
YoloV8ClassificationRuntimeSessionInfo = ClassificationRuntimeSessionInfo
YoloV8ClassificationPredictionRequest = ClassificationPredictionRequest
YoloV8ClassificationPredictionCategory = ClassificationPredictionCategory
YoloV8ClassificationPredictionExecutionResult = ClassificationPredictionExecutionResult


class YoloV8ClassificationPredictionSession(Protocol):
    """定义可重复执行的 YOLOv8 classification runtime session 接口。"""

    def predict(
        self,
        request: YoloV8ClassificationPredictionRequest,
    ) -> YoloV8ClassificationPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。"""


class YoloV8ClassificationPredictor(Protocol):
    """定义 YOLOv8 classification 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: YoloV8ClassificationPredictionRequest,
    ) -> YoloV8ClassificationPredictionExecutionResult:
        """执行一次单图预测。"""


def resolve_yolov8_classification_top_k(
    *,
    request: YoloV8ClassificationPredictionRequest,
    class_count: int,
) -> int:
    """返回当前请求实际使用的 top-k 值。"""

    if request.top_k <= 0:
        raise InvalidRequestError("top_k 必须大于 0", details={"top_k": request.top_k})
    return min(int(request.top_k), int(class_count))


__all__ = [
    "YoloV8ClassificationPredictionCategory",
    "YoloV8ClassificationPredictionExecutionResult",
    "YoloV8ClassificationPredictionRequest",
    "YoloV8ClassificationPredictionSession",
    "YoloV8ClassificationPredictor",
    "YoloV8ClassificationRuntimeSessionInfo",
    "YoloV8ClassificationRuntimeTensorSpec",
    "resolve_yolov8_classification_top_k",
]
