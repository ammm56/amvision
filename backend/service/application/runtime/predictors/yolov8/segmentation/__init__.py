"""YOLOv8 segmentation deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8.segmentation.onnxruntime import (
    OnnxRuntimeYoloV8SegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.openvino import (
    OpenVINOYoloV8SegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.pytorch import (
    PyTorchYoloV8SegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.tensorrt import (
    TensorRTYoloV8SegmentationRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYoloV8SegmentationRuntimeSession",
    "OpenVINOYoloV8SegmentationRuntimeSession",
    "PyTorchYoloV8SegmentationRuntimeSession",
    "TensorRTYoloV8SegmentationRuntimeSession",
]
