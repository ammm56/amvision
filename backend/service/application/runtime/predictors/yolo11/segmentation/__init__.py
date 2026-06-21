"""YOLO11 segmentation deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo11.segmentation.onnxruntime import (
    OnnxRuntimeYolo11SegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.segmentation.openvino import (
    OpenVINOYolo11SegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.segmentation.pytorch import (
    PyTorchYolo11SegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.segmentation.tensorrt import (
    TensorRTYolo11SegmentationRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYolo11SegmentationRuntimeSession",
    "OpenVINOYolo11SegmentationRuntimeSession",
    "PyTorchYolo11SegmentationRuntimeSession",
    "TensorRTYolo11SegmentationRuntimeSession",
]
