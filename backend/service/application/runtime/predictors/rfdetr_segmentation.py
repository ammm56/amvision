"""RF-DETR segmentation deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.rfdetr_segmentation_onnxruntime import (
    OnnxRuntimeRfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr_segmentation_openvino import (
    OpenVINORfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr_segmentation_pytorch import (
    PyTorchRfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr_segmentation_tensorrt import (
    TensorRTRfdetrSegmentationRuntimeSession,
)


__all__ = [
    "OnnxRuntimeRfdetrSegmentationRuntimeSession",
    "OpenVINORfdetrSegmentationRuntimeSession",
    "PyTorchRfdetrSegmentationRuntimeSession",
    "TensorRTRfdetrSegmentationRuntimeSession",
]
