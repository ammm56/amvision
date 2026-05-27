"""YOLO11 segmentation 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_segmentation_predictor import (
    OnnxRuntimeYoloPrimarySegmentationRuntimeSession,
    PyTorchYoloPrimarySegmentationRuntimeSession,
)


class PyTorchYolo11SegmentationRuntimeSession(PyTorchYoloPrimarySegmentationRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLO11 segmentation 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"


class OnnxRuntimeYolo11SegmentationRuntimeSession(OnnxRuntimeYoloPrimarySegmentationRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLO11 segmentation 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"


__all__ = [
    "PyTorchYolo11SegmentationRuntimeSession",
    "OnnxRuntimeYolo11SegmentationRuntimeSession",
]
