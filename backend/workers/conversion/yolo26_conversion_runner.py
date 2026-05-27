"""YOLO26 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.runtime.yolo26_classification_predictor import (
    PyTorchYolo26ClassificationRuntimeSession,
)
from backend.service.application.runtime.yolo26_segmentation_predictor import (
    PyTorchYolo26SegmentationRuntimeSession,
)
from backend.service.application.runtime.yolo26_predictor import PyTorchYolo26RuntimeSession
from backend.service.domain.files.yolo26_file_types import (
    YOLO26_ONNX_FILE,
    YOLO26_ONNX_OPTIMIZED_FILE,
    YOLO26_OPENVINO_IR_FILE,
    YOLO26_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolo_primary_conversion_runner import (
    LocalYoloPrimaryConversionRunner,
)


Yolo26ConversionRunRequest = ConversionBackendRunRequest
Yolo26ConversionOutput = ConversionBackendOutput
Yolo26ConversionRunResult = ConversionBackendRunResult
Yolo26ConversionRunner = ConversionBackend


class LocalYolo26ConversionRunner(LocalYoloPrimaryConversionRunner):
    """使用本地文件存储执行 YOLO26 ONNX/OpenVINO/TensorRT 转换链。"""

    model_label = "YOLO26"
    task_runtime_session_classes = {
        "detection": PyTorchYolo26RuntimeSession,
        "classification": PyTorchYolo26ClassificationRuntimeSession,
        "segmentation": PyTorchYolo26SegmentationRuntimeSession,
    }
    onnx_file_type = YOLO26_ONNX_FILE
    onnx_optimized_file_type = YOLO26_ONNX_OPTIMIZED_FILE
    openvino_ir_file_type = YOLO26_OPENVINO_IR_FILE
    tensorrt_engine_file_type = YOLO26_TENSORRT_ENGINE_FILE

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地 YOLO26 转换 runner。"""

        super().__init__(dataset_storage=dataset_storage)
