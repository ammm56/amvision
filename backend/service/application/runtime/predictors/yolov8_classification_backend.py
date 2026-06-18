"""YOLOv8 classification runtime 后端依赖和输出归一化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolov8_core.inference import (
    normalize_yolov8_classification_inference_outputs,
)
from backend.service.application.runtime.predictors.yolov8_segmentation_backend import (
    build_yolov8_segmentation_openvino_compile_properties,
    enable_yolov8_segmentation_cuda_fast_path,
    ensure_yolov8_segmentation_cuda_success,
    get_yolov8_segmentation_tensorrt_logger,
    import_yolov8_segmentation_onnxruntime_module,
    import_yolov8_segmentation_openvino_module,
    import_yolov8_segmentation_tensorrt_module,
    normalize_yolov8_segmentation_openvino_type_name,
    normalize_yolov8_segmentation_tensor_shape,
    release_yolov8_segmentation_cuda_resource,
    require_yolov8_segmentation_cuda_imports,
    require_yolov8_segmentation_inference_imports,
    require_yolov8_segmentation_pytorch_imports,
    resolve_yolov8_segmentation_cuda_device_index,
    resolve_yolov8_segmentation_cuda_runtime_device_name,
    resolve_yolov8_segmentation_onnxruntime_providers,
    resolve_yolov8_segmentation_openvino_compiled_runtime_precision,
    resolve_yolov8_segmentation_openvino_device_name,
    resolve_yolov8_segmentation_openvino_port_dtype,
    resolve_yolov8_segmentation_openvino_port_name,
    resolve_yolov8_segmentation_tensorrt_dtype_name,
    resolve_yolov8_segmentation_tensorrt_io_tensor_name,
    resolve_yolov8_segmentation_torch_device_name,
)


@dataclass(frozen=True)
class YoloV8ClassificationInferenceImports:
    """描述 YOLOv8 classification 基础推理依赖。"""

    cv2: Any
    np: Any


@dataclass(frozen=True)
class YoloV8ClassificationPytorchInferenceImports(YoloV8ClassificationInferenceImports):
    """描述 YOLOv8 classification PyTorch 推理依赖。"""

    torch: Any


@dataclass(frozen=True)
class YoloV8ClassificationCudaInferenceImports(YoloV8ClassificationInferenceImports):
    """描述 YOLOv8 classification TensorRT/CUDA 推理依赖。"""

    cudart: Any


def require_yolov8_classification_inference_imports() -> YoloV8ClassificationInferenceImports:
    """按需导入基础推理依赖。"""

    imports = require_yolov8_segmentation_inference_imports()
    return YoloV8ClassificationInferenceImports(cv2=imports.cv2, np=imports.np)


def require_yolov8_classification_pytorch_imports() -> YoloV8ClassificationPytorchInferenceImports:
    """按需导入 PyTorch 推理依赖。"""

    imports = require_yolov8_segmentation_pytorch_imports()
    return YoloV8ClassificationPytorchInferenceImports(
        cv2=imports.cv2,
        np=imports.np,
        torch=imports.torch,
    )


def require_yolov8_classification_cuda_imports() -> YoloV8ClassificationCudaInferenceImports:
    """按需导入 TensorRT/CUDA 推理依赖。"""

    imports = require_yolov8_segmentation_cuda_imports()
    return YoloV8ClassificationCudaInferenceImports(
        cv2=imports.cv2,
        np=imports.np,
        cudart=imports.cudart,
    )


def normalize_yolov8_classification_outputs_for_backend(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any | None]:
    """把后端输出统一转换为 YOLOv8 classification probabilities/logits。"""

    return normalize_yolov8_classification_inference_outputs(
        outputs=outputs,
        np_module=np_module,
    )


def resolve_yolov8_classification_single_output(
    *,
    outputs: Any,
    output_port: Any,
    output_name: str,
) -> Any:
    """从 OpenVINO 输出字典中取出单个 classification 输出。"""

    raw_output = outputs.get(output_port)
    if raw_output is None:
        raw_output = outputs.get(output_name)
    if raw_output is None and hasattr(outputs, "values"):
        values = tuple(outputs.values())
        raw_output = values[0] if values else None
    if raw_output is None:
        raise InvalidRequestError("openvino classification 推理输出为空")
    return raw_output


import_yolov8_classification_onnxruntime_module = import_yolov8_segmentation_onnxruntime_module
import_yolov8_classification_openvino_module = import_yolov8_segmentation_openvino_module
import_yolov8_classification_tensorrt_module = import_yolov8_segmentation_tensorrt_module
resolve_yolov8_classification_onnxruntime_providers = resolve_yolov8_segmentation_onnxruntime_providers
resolve_yolov8_classification_openvino_device_name = resolve_yolov8_segmentation_openvino_device_name
resolve_yolov8_classification_openvino_compiled_runtime_precision = (
    resolve_yolov8_segmentation_openvino_compiled_runtime_precision
)
resolve_yolov8_classification_openvino_port_dtype = resolve_yolov8_segmentation_openvino_port_dtype
resolve_yolov8_classification_openvino_port_name = resolve_yolov8_segmentation_openvino_port_name
resolve_yolov8_classification_torch_device_name = resolve_yolov8_segmentation_torch_device_name
enable_yolov8_classification_cuda_fast_path = enable_yolov8_segmentation_cuda_fast_path
ensure_yolov8_classification_cuda_success = ensure_yolov8_segmentation_cuda_success
release_yolov8_classification_cuda_resource = release_yolov8_segmentation_cuda_resource
get_yolov8_classification_tensorrt_logger = get_yolov8_segmentation_tensorrt_logger
normalize_yolov8_classification_openvino_type_name = normalize_yolov8_segmentation_openvino_type_name
normalize_yolov8_classification_tensor_shape = normalize_yolov8_segmentation_tensor_shape
resolve_yolov8_classification_cuda_device_index = resolve_yolov8_segmentation_cuda_device_index
resolve_yolov8_classification_cuda_runtime_device_name = (
    resolve_yolov8_segmentation_cuda_runtime_device_name
)
resolve_yolov8_classification_tensorrt_dtype_name = resolve_yolov8_segmentation_tensorrt_dtype_name
resolve_yolov8_classification_tensorrt_io_tensor_name = (
    resolve_yolov8_segmentation_tensorrt_io_tensor_name
)


def build_yolov8_classification_openvino_compile_properties(
    *,
    openvino_module: Any,
    runtime_precision: str,
    requested_device_name: str,
) -> dict[object, object]:
    """按 runtime precision 构造 YOLOv8 classification OpenVINO compile_model 属性。"""

    return build_yolov8_segmentation_openvino_compile_properties(
        openvino_module=openvino_module,
        runtime_precision=runtime_precision,
        requested_device_name=requested_device_name,
    )


__all__ = [
    "YoloV8ClassificationCudaInferenceImports",
    "YoloV8ClassificationInferenceImports",
    "YoloV8ClassificationPytorchInferenceImports",
    "build_yolov8_classification_openvino_compile_properties",
    "enable_yolov8_classification_cuda_fast_path",
    "ensure_yolov8_classification_cuda_success",
    "get_yolov8_classification_tensorrt_logger",
    "import_yolov8_classification_onnxruntime_module",
    "import_yolov8_classification_openvino_module",
    "import_yolov8_classification_tensorrt_module",
    "normalize_yolov8_classification_outputs_for_backend",
    "normalize_yolov8_classification_tensor_shape",
    "release_yolov8_classification_cuda_resource",
    "require_yolov8_classification_cuda_imports",
    "require_yolov8_classification_inference_imports",
    "require_yolov8_classification_pytorch_imports",
    "resolve_yolov8_classification_cuda_device_index",
    "resolve_yolov8_classification_cuda_runtime_device_name",
    "resolve_yolov8_classification_onnxruntime_providers",
    "resolve_yolov8_classification_openvino_compiled_runtime_precision",
    "resolve_yolov8_classification_openvino_device_name",
    "resolve_yolov8_classification_openvino_port_dtype",
    "resolve_yolov8_classification_openvino_port_name",
    "resolve_yolov8_classification_single_output",
    "resolve_yolov8_classification_tensorrt_dtype_name",
    "resolve_yolov8_classification_tensorrt_io_tensor_name",
    "resolve_yolov8_classification_torch_device_name",
]
