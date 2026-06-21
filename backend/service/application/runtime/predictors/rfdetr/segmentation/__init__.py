"""RF-DETR segmentation deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.rfdetr.segmentation.onnxruntime import (
    OnnxRuntimeRfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.openvino import (
    OpenVINORfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.pytorch import (
    PyTorchRfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.tensorrt import (
    TensorRTRfdetrSegmentationRuntimeSession,
)


__all__ = [
    "OnnxRuntimeRfdetrSegmentationRuntimeSession",
    "OpenVINORfdetrSegmentationRuntimeSession",
    "PyTorchRfdetrSegmentationRuntimeSession",
    "TensorRTRfdetrSegmentationRuntimeSession",
]
