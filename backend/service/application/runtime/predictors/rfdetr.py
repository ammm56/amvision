"""RF-DETR detection deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.rfdetr_onnxruntime import (
    OnnxRuntimeRfdetrRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr_openvino import (
    OpenVINORfdetrRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr_pytorch import (
    PyTorchRfdetrRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr_tensorrt_detection import (
    TensorRTRfdetrRuntimeSession,
)


__all__ = [
    "OnnxRuntimeRfdetrRuntimeSession",
    "OpenVINORfdetrRuntimeSession",
    "PyTorchRfdetrRuntimeSession",
    "TensorRTRfdetrRuntimeSession",
]
