"""YOLO26 segmentation 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_segmentation_predictor import (
    OnnxRuntimeYoloPrimarySegmentationRuntimeSession,
    PyTorchYoloPrimarySegmentationRuntimeSession,
)


class PyTorchYolo26SegmentationRuntimeSession(PyTorchYoloPrimarySegmentationRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLO26 segmentation 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


class OnnxRuntimeYolo26SegmentationRuntimeSession(OnnxRuntimeYoloPrimarySegmentationRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLO26 segmentation 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


__all__ = [
    "PyTorchYolo26SegmentationRuntimeSession",
    "OnnxRuntimeYolo26SegmentationRuntimeSession",
]
