"""YOLOX detection deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolox_backend import (
    build_yolox_openvino_compile_properties as _build_openvino_compile_properties,
    ensure_yolox_cuda_success as _ensure_cuda_success,
    get_yolox_tensorrt_logger as _get_tensorrt_logger,
    import_yolox_onnxruntime_module as _import_onnxruntime_module,
    import_yolox_openvino_module as _import_openvino_module,
    import_yolox_tensorrt_module as _import_tensorrt_module,
    normalize_yolox_onnxruntime_outputs as _normalize_onnxruntime_outputs,
    normalize_yolox_openvino_outputs as _normalize_openvino_outputs,
    normalize_yolox_tensor_shape as _normalize_tensor_shape,
    normalize_yolox_tensorrt_outputs as _normalize_tensorrt_outputs,
    require_yolox_cuda_inference_imports as _require_cuda_inference_imports,
    require_yolox_inference_imports as _require_inference_imports,
    resolve_yolox_cuda_device_index as _resolve_cuda_device_index,
    resolve_yolox_cuda_runtime_device_name as _resolve_cuda_runtime_device_name,
    resolve_yolox_onnxruntime_providers as _resolve_onnxruntime_providers,
    resolve_yolox_openvino_compiled_runtime_precision as _resolve_openvino_compiled_runtime_precision,
    resolve_yolox_openvino_device_name as _resolve_openvino_device_name,
    resolve_yolox_openvino_port_dtype as _resolve_openvino_port_dtype,
    resolve_yolox_openvino_port_name as _resolve_openvino_port_name,
    resolve_yolox_tensorrt_dtype_name as _resolve_tensorrt_dtype_name,
    resolve_yolox_tensorrt_io_tensor_name as _resolve_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.predictors.yolox_buffer import (
    resolve_yolox_numpy_dtype as _resolve_numpy_dtype,
)
from backend.service.application.runtime.predictors.yolox_contracts import (
    DEFAULT_YOLOX_NMS_THRESHOLD as _DEFAULT_NMS_THRESHOLD,
    RuntimeTensorSpec,
    YoloXPredictionDetection,
    YoloXPredictionExecutionResult,
    YoloXPredictionRequest,
    YoloXPredictionSession,
    YoloXPredictor,
    YoloXRuntimeSessionInfo,
    resolve_yolox_probability as _resolve_probability,
)
from backend.service.application.runtime.predictors.yolox_io import (
    load_yolox_prediction_image as _load_prediction_image,
    preprocess_yolox_image as _preprocess_image,
)
from backend.service.application.runtime.predictors.yolox_onnxruntime import (
    OnnxRuntimeYoloXRuntimeSession,
)
from backend.service.application.runtime.predictors.yolox_openvino import (
    OpenVINOYoloXRuntimeSession,
)
from backend.service.application.runtime.predictors.yolox_pytorch import (
    PyTorchYoloXPredictor,
    PyTorchYoloXRuntimeSession,
)
from backend.service.application.runtime.predictors.yolox_serialization import (
    serialize_yolox_detection as serialize_detection,
    serialize_yolox_runtime_session_info as serialize_runtime_session_info,
)
from backend.service.application.runtime.predictors.yolox_tensorrt import (
    TensorRTYoloXRuntimeSession,
)
from backend.service.application.runtime.predictors.yolox_timing import (
    measure_yolox_cuda_event_elapsed_ms as _measure_cuda_event_elapsed_ms,
    measure_yolox_stage_elapsed_ms as _measure_stage_elapsed_ms,
)


# Detection 公共层别名，用于逐步收口 YOLOX 命名到 detection 公共层。
PyTorchDetectionRuntimeSession = PyTorchYoloXRuntimeSession
OnnxRuntimeDetectionRuntimeSession = OnnxRuntimeYoloXRuntimeSession
OpenVINODetectionRuntimeSession = OpenVINOYoloXRuntimeSession
TensorRTDetectionRuntimeSession = TensorRTYoloXRuntimeSession


__all__ = [
    "OpenVINODetectionRuntimeSession",
    "OpenVINOYoloXRuntimeSession",
    "OnnxRuntimeDetectionRuntimeSession",
    "OnnxRuntimeYoloXRuntimeSession",
    "PyTorchDetectionRuntimeSession",
    "PyTorchYoloXPredictor",
    "PyTorchYoloXRuntimeSession",
    "RuntimeTensorSpec",
    "TensorRTDetectionRuntimeSession",
    "TensorRTYoloXRuntimeSession",
    "YoloXPredictionDetection",
    "YoloXPredictionExecutionResult",
    "YoloXPredictionRequest",
    "YoloXPredictionSession",
    "YoloXPredictor",
    "YoloXRuntimeSessionInfo",
    "_DEFAULT_NMS_THRESHOLD",
    "_build_openvino_compile_properties",
    "_ensure_cuda_success",
    "_get_tensorrt_logger",
    "_import_onnxruntime_module",
    "_import_openvino_module",
    "_import_tensorrt_module",
    "_load_prediction_image",
    "_measure_cuda_event_elapsed_ms",
    "_measure_stage_elapsed_ms",
    "_normalize_onnxruntime_outputs",
    "_normalize_openvino_outputs",
    "_normalize_tensor_shape",
    "_normalize_tensorrt_outputs",
    "_preprocess_image",
    "_require_cuda_inference_imports",
    "_require_inference_imports",
    "_resolve_cuda_device_index",
    "_resolve_cuda_runtime_device_name",
    "_resolve_numpy_dtype",
    "_resolve_onnxruntime_providers",
    "_resolve_openvino_compiled_runtime_precision",
    "_resolve_openvino_device_name",
    "_resolve_openvino_port_dtype",
    "_resolve_openvino_port_name",
    "_resolve_probability",
    "_resolve_tensorrt_dtype_name",
    "_resolve_tensorrt_io_tensor_name",
    "serialize_detection",
    "serialize_runtime_session_info",
]
