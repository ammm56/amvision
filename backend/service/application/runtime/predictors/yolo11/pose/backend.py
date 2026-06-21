"""YOLO11 pose runtime 后端依赖和输出归一化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo11_core.inference import (
    normalize_yolo11_pose_inference_outputs,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.backend import (
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
class Yolo11PoseInferenceImports:
    """描述 YOLO11 pose 基础推理依赖。"""

    cv2: Any
    np: Any


@dataclass(frozen=True)
class Yolo11PosePytorchInferenceImports(Yolo11PoseInferenceImports):
    """描述 YOLO11 pose PyTorch 推理依赖。"""

    torch: Any


@dataclass(frozen=True)
class Yolo11PoseCudaInferenceImports(Yolo11PoseInferenceImports):
    """描述 YOLO11 pose TensorRT/CUDA 推理依赖。"""

    cudart: Any


def require_yolo11_pose_inference_imports() -> Yolo11PoseInferenceImports:
    """按需导入基础推理依赖。"""

    imports = require_yolov8_segmentation_inference_imports()
    return Yolo11PoseInferenceImports(cv2=imports.cv2, np=imports.np)


def require_yolo11_pose_pytorch_imports() -> Yolo11PosePytorchInferenceImports:
    """按需导入 PyTorch 推理依赖。"""

    imports = require_yolov8_segmentation_pytorch_imports()
    return Yolo11PosePytorchInferenceImports(
        cv2=imports.cv2, np=imports.np, torch=imports.torch
    )


def require_yolo11_pose_cuda_imports() -> Yolo11PoseCudaInferenceImports:
    """按需导入 TensorRT/CUDA 推理依赖。"""

    imports = require_yolov8_segmentation_cuda_imports()
    return Yolo11PoseCudaInferenceImports(
        cv2=imports.cv2, np=imports.np, cudart=imports.cudart
    )


def normalize_yolo11_pose_outputs_for_backend(
    *, outputs: object, np_module: Any
) -> Any:
    """把后端输出统一转换为 YOLO11 pose prediction array。"""

    return normalize_yolo11_pose_inference_outputs(outputs=outputs, np_module=np_module)


import_yolo11_pose_onnxruntime_module = import_yolov8_segmentation_onnxruntime_module
import_yolo11_pose_openvino_module = import_yolov8_segmentation_openvino_module
import_yolo11_pose_tensorrt_module = import_yolov8_segmentation_tensorrt_module
resolve_yolo11_pose_onnxruntime_providers = (
    resolve_yolov8_segmentation_onnxruntime_providers
)
resolve_yolo11_pose_openvino_device_name = (
    resolve_yolov8_segmentation_openvino_device_name
)
resolve_yolo11_pose_openvino_compiled_runtime_precision = (
    resolve_yolov8_segmentation_openvino_compiled_runtime_precision
)
resolve_yolo11_pose_openvino_port_dtype = (
    resolve_yolov8_segmentation_openvino_port_dtype
)
resolve_yolo11_pose_openvino_port_name = resolve_yolov8_segmentation_openvino_port_name
resolve_yolo11_pose_torch_device_name = resolve_yolov8_segmentation_torch_device_name
enable_yolo11_pose_cuda_fast_path = enable_yolov8_segmentation_cuda_fast_path
ensure_yolo11_pose_cuda_success = ensure_yolov8_segmentation_cuda_success
release_yolo11_pose_cuda_resource = release_yolov8_segmentation_cuda_resource
get_yolo11_pose_tensorrt_logger = get_yolov8_segmentation_tensorrt_logger
normalize_yolo11_pose_tensor_shape = normalize_yolov8_segmentation_tensor_shape
resolve_yolo11_pose_cuda_device_index = resolve_yolov8_segmentation_cuda_device_index
resolve_yolo11_pose_cuda_runtime_device_name = (
    resolve_yolov8_segmentation_cuda_runtime_device_name
)
resolve_yolo11_pose_tensorrt_dtype_name = (
    resolve_yolov8_segmentation_tensorrt_dtype_name
)
resolve_yolo11_pose_tensorrt_io_tensor_name = (
    resolve_yolov8_segmentation_tensorrt_io_tensor_name
)


def build_yolo11_pose_openvino_compile_properties(
    *,
    openvino_module: Any,
    runtime_precision: str,
    requested_device_name: str,
) -> dict[object, object]:
    """按 runtime precision 构造 YOLO11 pose OpenVINO compile_model 属性。"""

    return build_yolov8_segmentation_openvino_compile_properties(
        openvino_module=openvino_module,
        runtime_precision=runtime_precision,
        requested_device_name=requested_device_name,
    )


__all__ = [
    "Yolo11PoseCudaInferenceImports",
    "Yolo11PoseInferenceImports",
    "Yolo11PosePytorchInferenceImports",
    "build_yolo11_pose_openvino_compile_properties",
    "enable_yolo11_pose_cuda_fast_path",
    "ensure_yolo11_pose_cuda_success",
    "get_yolo11_pose_tensorrt_logger",
    "import_yolo11_pose_onnxruntime_module",
    "import_yolo11_pose_openvino_module",
    "import_yolo11_pose_tensorrt_module",
    "normalize_yolo11_pose_outputs_for_backend",
    "normalize_yolo11_pose_tensor_shape",
    "release_yolo11_pose_cuda_resource",
    "require_yolo11_pose_cuda_imports",
    "require_yolo11_pose_inference_imports",
    "require_yolo11_pose_pytorch_imports",
    "resolve_yolo11_pose_cuda_device_index",
    "resolve_yolo11_pose_cuda_runtime_device_name",
    "resolve_yolo11_pose_onnxruntime_providers",
    "resolve_yolo11_pose_openvino_compiled_runtime_precision",
    "resolve_yolo11_pose_openvino_device_name",
    "resolve_yolo11_pose_openvino_port_dtype",
    "resolve_yolo11_pose_openvino_port_name",
    "resolve_yolo11_pose_tensorrt_dtype_name",
    "resolve_yolo11_pose_tensorrt_io_tensor_name",
    "resolve_yolo11_pose_torch_device_name",
]
