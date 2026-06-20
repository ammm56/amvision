"""YOLO26 OBB runtime 后端依赖和输出归一化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo26_core.inference import (
    normalize_yolo26_obb_inference_outputs,
)
from backend.service.application.runtime.predictors.yolov8_segmentation_backend import (
    build_yolov8_segmentation_openvino_compile_properties,
    enable_yolov8_segmentation_cuda_fast_path,
    ensure_yolov8_segmentation_cuda_success,
    get_yolov8_segmentation_tensorrt_logger,
    import_yolov8_segmentation_onnxruntime_module,
    import_yolov8_segmentation_openvino_module,
    import_yolov8_segmentation_tensorrt_module,
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
class Yolo26ObbInferenceImports:
    """描述 YOLO26 OBB 基础推理依赖。"""

    cv2: Any
    np: Any


@dataclass(frozen=True)
class Yolo26ObbPytorchInferenceImports(Yolo26ObbInferenceImports):
    """描述 YOLO26 OBB PyTorch 推理依赖。"""

    torch: Any


@dataclass(frozen=True)
class Yolo26ObbCudaInferenceImports(Yolo26ObbInferenceImports):
    """描述 YOLO26 OBB TensorRT/CUDA 推理依赖。"""

    cudart: Any


def require_yolo26_obb_inference_imports() -> Yolo26ObbInferenceImports:
    """按需导入基础推理依赖。"""

    imports = require_yolov8_segmentation_inference_imports()
    return Yolo26ObbInferenceImports(cv2=imports.cv2, np=imports.np)


def require_yolo26_obb_pytorch_imports() -> Yolo26ObbPytorchInferenceImports:
    """按需导入 PyTorch 推理依赖。"""

    imports = require_yolov8_segmentation_pytorch_imports()
    return Yolo26ObbPytorchInferenceImports(
        cv2=imports.cv2, np=imports.np, torch=imports.torch
    )


def require_yolo26_obb_cuda_imports() -> Yolo26ObbCudaInferenceImports:
    """按需导入 TensorRT/CUDA 推理依赖。"""

    imports = require_yolov8_segmentation_cuda_imports()
    return Yolo26ObbCudaInferenceImports(
        cv2=imports.cv2, np=imports.np, cudart=imports.cudart
    )


def normalize_yolo26_obb_outputs_for_backend(*, outputs: object, np_module: Any) -> Any:
    """把后端输出统一转换为 YOLO26 OBB prediction array。"""

    return normalize_yolo26_obb_inference_outputs(outputs=outputs, np_module=np_module)


import_yolo26_obb_onnxruntime_module = import_yolov8_segmentation_onnxruntime_module
import_yolo26_obb_openvino_module = import_yolov8_segmentation_openvino_module
import_yolo26_obb_tensorrt_module = import_yolov8_segmentation_tensorrt_module
resolve_yolo26_obb_onnxruntime_providers = (
    resolve_yolov8_segmentation_onnxruntime_providers
)
resolve_yolo26_obb_openvino_device_name = (
    resolve_yolov8_segmentation_openvino_device_name
)
resolve_yolo26_obb_openvino_compiled_runtime_precision = (
    resolve_yolov8_segmentation_openvino_compiled_runtime_precision
)
resolve_yolo26_obb_openvino_port_dtype = resolve_yolov8_segmentation_openvino_port_dtype
resolve_yolo26_obb_openvino_port_name = resolve_yolov8_segmentation_openvino_port_name
resolve_yolo26_obb_torch_device_name = resolve_yolov8_segmentation_torch_device_name
enable_yolo26_obb_cuda_fast_path = enable_yolov8_segmentation_cuda_fast_path
ensure_yolo26_obb_cuda_success = ensure_yolov8_segmentation_cuda_success
release_yolo26_obb_cuda_resource = release_yolov8_segmentation_cuda_resource
get_yolo26_obb_tensorrt_logger = get_yolov8_segmentation_tensorrt_logger
normalize_yolo26_obb_tensor_shape = normalize_yolov8_segmentation_tensor_shape
resolve_yolo26_obb_cuda_device_index = resolve_yolov8_segmentation_cuda_device_index
resolve_yolo26_obb_cuda_runtime_device_name = (
    resolve_yolov8_segmentation_cuda_runtime_device_name
)
resolve_yolo26_obb_tensorrt_dtype_name = resolve_yolov8_segmentation_tensorrt_dtype_name
resolve_yolo26_obb_tensorrt_io_tensor_name = (
    resolve_yolov8_segmentation_tensorrt_io_tensor_name
)


def build_yolo26_obb_openvino_compile_properties(
    *,
    openvino_module: Any,
    runtime_precision: str,
    requested_device_name: str,
) -> dict[object, object]:
    """按 runtime precision 构造 YOLO26 OBB OpenVINO compile_model 属性。"""

    return build_yolov8_segmentation_openvino_compile_properties(
        openvino_module=openvino_module,
        runtime_precision=runtime_precision,
        requested_device_name=requested_device_name,
    )


__all__ = [
    "Yolo26ObbCudaInferenceImports",
    "Yolo26ObbInferenceImports",
    "Yolo26ObbPytorchInferenceImports",
    "build_yolo26_obb_openvino_compile_properties",
    "enable_yolo26_obb_cuda_fast_path",
    "ensure_yolo26_obb_cuda_success",
    "get_yolo26_obb_tensorrt_logger",
    "import_yolo26_obb_onnxruntime_module",
    "import_yolo26_obb_openvino_module",
    "import_yolo26_obb_tensorrt_module",
    "normalize_yolo26_obb_outputs_for_backend",
    "normalize_yolo26_obb_tensor_shape",
    "release_yolo26_obb_cuda_resource",
    "require_yolo26_obb_cuda_imports",
    "require_yolo26_obb_inference_imports",
    "require_yolo26_obb_pytorch_imports",
    "resolve_yolo26_obb_cuda_device_index",
    "resolve_yolo26_obb_cuda_runtime_device_name",
    "resolve_yolo26_obb_onnxruntime_providers",
    "resolve_yolo26_obb_openvino_compiled_runtime_precision",
    "resolve_yolo26_obb_openvino_device_name",
    "resolve_yolo26_obb_openvino_port_dtype",
    "resolve_yolo26_obb_openvino_port_name",
    "resolve_yolo26_obb_tensorrt_dtype_name",
    "resolve_yolo26_obb_tensorrt_io_tensor_name",
    "resolve_yolo26_obb_torch_device_name",
]
