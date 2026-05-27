"""YOLOX 历史命名的 detection 运行时契约别名。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.runtime.detection_runtime_contracts import (
    DetectionPredictionDetection,
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)


RuntimeTensorSpec = DetectionRuntimeTensorSpec
YoloXRuntimeSessionInfo = DetectionRuntimeSessionInfo
YoloXRuntimePredictRequest = DetectionPredictionRequest
YoloXRuntimePredictResult = DetectionPredictionExecutionResult


class YoloXRuntimeSession(Protocol):
    """保留旧命名的运行时会话协议别名。"""

    def describe(self) -> DetectionRuntimeSessionInfo:
        """返回当前运行时会话信息。"""

        ...

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        """执行一次预测。"""

        ...

__all__ = [
    "RuntimeTensorSpec",
    "YoloXRuntimeSessionInfo",
    "YoloXRuntimePredictRequest",
    "YoloXRuntimePredictResult",
    "YoloXRuntimeSession",
    "DetectionRuntimeTensorSpec",
    "DetectionRuntimeSessionInfo",
    "DetectionPredictionRequest",
    "DetectionPredictionDetection",
    "DetectionPredictionExecutionResult",
]
