"""YOLO11 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.runtime.yolo11_predictor import PyTorchYolo11RuntimeSession
from backend.service.domain.files.yolo11_file_types import (
    YOLO11_ONNX_FILE,
    YOLO11_ONNX_OPTIMIZED_FILE,
    YOLO11_OPENVINO_IR_FILE,
    YOLO11_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolo_primary_conversion_runner import (
    LocalYoloPrimaryConversionRunner,
)


Yolo11ConversionRunRequest = ConversionBackendRunRequest
Yolo11ConversionOutput = ConversionBackendOutput
Yolo11ConversionRunResult = ConversionBackendRunResult
Yolo11ConversionRunner = ConversionBackend


class LocalYolo11ConversionRunner(LocalYoloPrimaryConversionRunner):
    """使用本地文件存储执行 YOLO11 ONNX/OpenVINO/TensorRT 转换链。"""

    model_label = "YOLO11"
    pytorch_runtime_session_cls = PyTorchYolo11RuntimeSession
    onnx_file_type = YOLO11_ONNX_FILE
    onnx_optimized_file_type = YOLO11_ONNX_OPTIMIZED_FILE
    openvino_ir_file_type = YOLO11_OPENVINO_IR_FILE
    tensorrt_engine_file_type = YOLO11_TENSORRT_ENGINE_FILE

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地 YOLO11 转换 runner。"""

        super().__init__(dataset_storage=dataset_storage)
