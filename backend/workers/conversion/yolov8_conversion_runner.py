"""YOLOv8 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.runtime.yolov8_predictor import PyTorchYoloV8RuntimeSession
from backend.service.domain.files.yolov8_file_types import (
    YOLOV8_ONNX_FILE,
    YOLOV8_ONNX_OPTIMIZED_FILE,
    YOLOV8_OPENVINO_IR_FILE,
    YOLOV8_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolo_primary_conversion_runner import (
    LocalYoloPrimaryConversionRunner,
)


YoloV8ConversionRunRequest = ConversionBackendRunRequest
YoloV8ConversionOutput = ConversionBackendOutput
YoloV8ConversionRunResult = ConversionBackendRunResult
YoloV8ConversionRunner = ConversionBackend


class LocalYoloV8ConversionRunner(LocalYoloPrimaryConversionRunner):
    """使用本地文件存储执行 YOLOv8 ONNX/OpenVINO/TensorRT 转换链。"""

    model_label = "YOLOv8"
    pytorch_runtime_session_cls = PyTorchYoloV8RuntimeSession
    onnx_file_type = YOLOV8_ONNX_FILE
    onnx_optimized_file_type = YOLOV8_ONNX_OPTIMIZED_FILE
    openvino_ir_file_type = YOLOV8_OPENVINO_IR_FILE
    tensorrt_engine_file_type = YOLOV8_TENSORRT_ENGINE_FILE

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地 YOLOv8 转换 runner。"""

        super().__init__(dataset_storage=dataset_storage)


__all__ = [
    "YoloV8ConversionRunRequest",
    "YoloV8ConversionOutput",
    "YoloV8ConversionRunResult",
    "YoloV8ConversionRunner",
    "LocalYoloV8ConversionRunner",
]
