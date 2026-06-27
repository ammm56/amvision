"""detection 运行时共享支持工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
    letterbox_yolo_image,
)
from backend.service.application.models.yolox_core.postprocess import (
    batched_yolox_nms_indices as batched_nms_indices,
    yolox_prediction_to_numpy_array as prediction_to_numpy_array,
)
from backend.service.application.models.yolox_core.utils import (
    enable_yolox_cuda_inference_fast_path as enable_pytorch_cuda_inference_fast_path,
    resolve_yolox_torch_device_name as resolve_execution_device_name,
)
from backend.service.application.runtime.predictors.yolox import (
    OpenVINOYoloXRuntimeSession as OpenVINODetectionRuntimeSessionBase,
    TensorRTYoloXRuntimeSession as TensorRTDetectionRuntimeSessionBase,
    _DEFAULT_NMS_THRESHOLD as DEFAULT_DETECTION_NMS_THRESHOLD,
    _build_openvino_compile_properties as build_openvino_compile_properties,
    _ensure_cuda_success as ensure_cuda_success,
    _get_tensorrt_logger as get_tensorrt_logger,
    _import_openvino_module as import_openvino_module,
    _import_tensorrt_module as import_tensorrt_module,
    _import_onnxruntime_module as import_onnxruntime_module,
    _load_prediction_image as load_prediction_image,
    _measure_stage_elapsed_ms as measure_stage_elapsed_ms,
    _measure_cuda_event_elapsed_ms as measure_cuda_event_elapsed_ms,
    _normalize_onnxruntime_outputs as normalize_onnxruntime_outputs,
    _normalize_openvino_outputs as normalize_openvino_outputs,
    _normalize_tensorrt_outputs as normalize_tensorrt_outputs,
    _normalize_tensor_shape as normalize_tensor_shape,
    _require_cuda_inference_imports as require_cuda_inference_imports,
    _require_inference_imports as require_inference_imports,
    _resolve_cuda_device_index as resolve_cuda_device_index,
    _resolve_cuda_runtime_device_name as resolve_cuda_runtime_device_name,
    _resolve_numpy_dtype as resolve_numpy_dtype,
    _resolve_onnxruntime_providers as resolve_onnxruntime_providers,
    _resolve_openvino_compiled_runtime_precision as _resolve_yolox_openvino_compiled_runtime_precision,
    _resolve_openvino_device_name as resolve_openvino_device_name,
    _resolve_openvino_port_dtype as resolve_openvino_port_dtype,
    _resolve_openvino_port_name as resolve_openvino_port_name,
    _resolve_probability as resolve_probability,
    _resolve_tensorrt_dtype_name as resolve_tensorrt_dtype_name,
    _resolve_tensorrt_io_tensor_name as resolve_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.predictors.yolox.backend import (
    release_yolox_cuda_resource as release_cuda_resource,
)
from backend.service.application.runtime.support.detection_preview import (
    render_detection_preview_image as render_preview_image,
)


def preprocess_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, YoloLetterboxTransform]:
    """按普通 YOLO detection LetterBox 规则构造输入张量和反算信息。"""

    letterboxed_image, transform = letterbox_yolo_image(
        cv2_module=cv2_module,
        np_module=np_module,
        image=image,
        input_size=input_size,
    )
    tensor = (
        letterboxed_image[:, :, ::-1].transpose(2, 0, 1).astype(np_module.float32)
        / 255.0
    )
    return np_module.ascontiguousarray(tensor, dtype=np_module.float32), transform


def resolve_openvino_compiled_runtime_precision(
    *,
    session: object | None = None,
    fallback_precision: str | None = None,
    requested_runtime_precision: str | None = None,
    compile_properties: dict[object, object] | None = None,
    fallback: str | None = None,
) -> str:
    """解析 OpenVINO 编译后实际使用的 runtime precision。

    参数：
    - session：已经编译完成的 OpenVINO session，可用于读取真实 precision hint。
    - fallback_precision：读取 session 失败时的回退 precision。
    - requested_runtime_precision：没有 session 时按请求 precision 记录 metadata。
    - compile_properties：OpenVINO compile_model 属性，用于区分是否显式请求 fp16。
    - fallback：没有 session 和请求值时使用的回退 precision。
    """

    resolved_fallback = (
        fallback_precision
        or requested_runtime_precision
        or fallback
        or "fp32"
    )
    if session is not None:
        return _resolve_yolox_openvino_compiled_runtime_precision(
            session=session,
            fallback_precision=resolved_fallback,
        )
    if requested_runtime_precision == "fp16" and compile_properties:
        return "fp16"
    return requested_runtime_precision or fallback or resolved_fallback


__all__ = [
    "DEFAULT_DETECTION_NMS_THRESHOLD",
    "OpenVINODetectionRuntimeSessionBase",
    "TensorRTDetectionRuntimeSessionBase",
    "batched_nms_indices",
    "build_openvino_compile_properties",
    "enable_pytorch_cuda_inference_fast_path",
    "ensure_cuda_success",
    "get_tensorrt_logger",
    "import_openvino_module",
    "import_onnxruntime_module",
    "import_tensorrt_module",
    "load_prediction_image",
    "measure_cuda_event_elapsed_ms",
    "measure_stage_elapsed_ms",
    "normalize_onnxruntime_outputs",
    "normalize_openvino_outputs",
    "normalize_tensor_shape",
    "normalize_tensorrt_outputs",
    "prediction_to_numpy_array",
    "preprocess_image",
    "render_preview_image",
    "require_cuda_inference_imports",
    "require_inference_imports",
    "release_cuda_resource",
    "resolve_cuda_device_index",
    "resolve_cuda_runtime_device_name",
    "resolve_execution_device_name",
    "resolve_numpy_dtype",
    "resolve_onnxruntime_providers",
    "resolve_openvino_compiled_runtime_precision",
    "resolve_openvino_device_name",
    "resolve_openvino_port_dtype",
    "resolve_openvino_port_name",
    "resolve_probability",
    "resolve_tensorrt_dtype_name",
    "resolve_tensorrt_io_tensor_name",
]
