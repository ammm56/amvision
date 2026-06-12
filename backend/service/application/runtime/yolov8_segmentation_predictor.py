"""YOLOv8 segmentation 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_segmentation_predictor import (
    OnnxRuntimeYoloPrimarySegmentationRuntimeSession,
    OpenVINOYoloPrimarySegmentationRuntimeSession,
    PyTorchYoloPrimarySegmentationRuntimeSession,
    TensorRTYoloPrimarySegmentationRuntimeSession,
)


class PyTorchYoloV8SegmentationRuntimeSession(PyTorchYoloPrimarySegmentationRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLOv8 segmentation 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


class OnnxRuntimeYoloV8SegmentationRuntimeSession(OnnxRuntimeYoloPrimarySegmentationRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLOv8 segmentation 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


class OpenVINOYoloV8SegmentationRuntimeSession(OpenVINOYoloPrimarySegmentationRuntimeSession):
    """已经加载完成并可重复推理的 OpenVINO YOLOv8 segmentation 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


class TensorRTYoloV8SegmentationRuntimeSession(TensorRTYoloPrimarySegmentationRuntimeSession):
    """已经加载完成并可重复推理的 TensorRT YOLOv8 segmentation 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


__all__ = [
    "PyTorchYoloV8SegmentationRuntimeSession",
    "OnnxRuntimeYoloV8SegmentationRuntimeSession",
    "OpenVINOYoloV8SegmentationRuntimeSession",
    "TensorRTYoloV8SegmentationRuntimeSession",
]
