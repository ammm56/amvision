"""YOLOv8 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from backend.workers.conversion.yolo_primary_conversion_runner import (
    LocalYoloPrimaryConversionRunner as LocalYoloV8ConversionRunner,
    YoloPrimaryConversionOutput as YoloV8ConversionOutput,
    YoloPrimaryConversionRunRequest as YoloV8ConversionRunRequest,
    YoloPrimaryConversionRunResult as YoloV8ConversionRunResult,
    YoloPrimaryConversionRunner as YoloV8ConversionRunner,
)


__all__ = [
    "YoloV8ConversionRunRequest",
    "YoloV8ConversionOutput",
    "YoloV8ConversionRunResult",
    "YoloV8ConversionRunner",
    "LocalYoloV8ConversionRunner",
]
