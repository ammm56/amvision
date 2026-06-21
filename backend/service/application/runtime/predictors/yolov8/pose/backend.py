"""YOLOv8 pose runtime 后端依赖和输出归一化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolov8_core.inference import (
    normalize_yolov8_pose_inference_outputs,
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
class YoloV8PoseInferenceImports:
    """描述 YOLOv8 pose 基础推理依赖。"""

    cv2: Any
    np: Any


@dataclass(frozen=True)
class YoloV8PosePytorchInferenceImports(YoloV8PoseInferenceImports):
    """描述 YOLOv8 pose PyTorch 推理依赖。"""

    torch: Any


@dataclass(frozen=True)
class YoloV8PoseCudaInferenceImports(YoloV8PoseInferenceImports):
    """描述 YOLOv8 pose TensorRT/CUDA 推理依赖。"""

    cudart: Any


def require_yolov8_pose_inference_imports() -> YoloV8PoseInferenceImports:
    """按需导入基础推理依赖。"""

    imports = require_yolov8_segmentation_inference_imports()
    return YoloV8PoseInferenceImports(cv2=imports.cv2, np=imports.np)


def require_yolov8_pose_pytorch_imports() -> YoloV8PosePytorchInferenceImports:
    """按需导入 PyTorch 推理依赖。"""

    imports = require_yolov8_segmentation_pytorch_imports()
    return YoloV8PosePytorchInferenceImports(cv2=imports.cv2, np=imports.np, torch=imports.torch)


def require_yolov8_pose_cuda_imports() -> YoloV8PoseCudaInferenceImports:
    """按需导入 TensorRT/CUDA 推理依赖。"""

    imports = require_yolov8_segmentation_cuda_imports()
    return YoloV8PoseCudaInferenceImports(cv2=imports.cv2, np=imports.np, cudart=imports.cudart)


def normalize_yolov8_pose_outputs_for_backend(*, outputs: object, np_module: Any) -> Any:
    """把后端输出统一转换为 YOLOv8 pose prediction array。"""

    return normalize_yolov8_pose_inference_outputs(outputs=outputs, np_module=np_module)


import_yolov8_pose_onnxruntime_module = import_yolov8_segmentation_onnxruntime_module
import_yolov8_pose_openvino_module = import_yolov8_segmentation_openvino_module
import_yolov8_pose_tensorrt_module = import_yolov8_segmentation_tensorrt_module
resolve_yolov8_pose_onnxruntime_providers = resolve_yolov8_segmentation_onnxruntime_providers
resolve_yolov8_pose_openvino_device_name = resolve_yolov8_segmentation_openvino_device_name
resolve_yolov8_pose_openvino_compiled_runtime_precision = (
    resolve_yolov8_segmentation_openvino_compiled_runtime_precision
)
resolve_yolov8_pose_openvino_port_dtype = resolve_yolov8_segmentation_openvino_port_dtype
resolve_yolov8_pose_openvino_port_name = resolve_yolov8_segmentation_openvino_port_name
resolve_yolov8_pose_torch_device_name = resolve_yolov8_segmentation_torch_device_name
enable_yolov8_pose_cuda_fast_path = enable_yolov8_segmentation_cuda_fast_path
ensure_yolov8_pose_cuda_success = ensure_yolov8_segmentation_cuda_success
release_yolov8_pose_cuda_resource = release_yolov8_segmentation_cuda_resource
get_yolov8_pose_tensorrt_logger = get_yolov8_segmentation_tensorrt_logger
normalize_yolov8_pose_tensor_shape = normalize_yolov8_segmentation_tensor_shape
resolve_yolov8_pose_cuda_device_index = resolve_yolov8_segmentation_cuda_device_index
resolve_yolov8_pose_cuda_runtime_device_name = resolve_yolov8_segmentation_cuda_runtime_device_name
resolve_yolov8_pose_tensorrt_dtype_name = resolve_yolov8_segmentation_tensorrt_dtype_name
resolve_yolov8_pose_tensorrt_io_tensor_name = resolve_yolov8_segmentation_tensorrt_io_tensor_name


def build_yolov8_pose_openvino_compile_properties(
    *,
    openvino_module: Any,
    runtime_precision: str,
    requested_device_name: str,
) -> dict[object, object]:
    """按 runtime precision 构造 YOLOv8 pose OpenVINO compile_model 属性。"""

    return build_yolov8_segmentation_openvino_compile_properties(
        openvino_module=openvino_module,
        runtime_precision=runtime_precision,
        requested_device_name=requested_device_name,
    )


__all__ = [
    "YoloV8PoseCudaInferenceImports",
    "YoloV8PoseInferenceImports",
    "YoloV8PosePytorchInferenceImports",
    "build_yolov8_pose_openvino_compile_properties",
    "enable_yolov8_pose_cuda_fast_path",
    "ensure_yolov8_pose_cuda_success",
    "get_yolov8_pose_tensorrt_logger",
    "import_yolov8_pose_onnxruntime_module",
    "import_yolov8_pose_openvino_module",
    "import_yolov8_pose_tensorrt_module",
    "normalize_yolov8_pose_outputs_for_backend",
    "normalize_yolov8_pose_tensor_shape",
    "release_yolov8_pose_cuda_resource",
    "require_yolov8_pose_cuda_imports",
    "require_yolov8_pose_inference_imports",
    "require_yolov8_pose_pytorch_imports",
    "resolve_yolov8_pose_cuda_device_index",
    "resolve_yolov8_pose_cuda_runtime_device_name",
    "resolve_yolov8_pose_onnxruntime_providers",
    "resolve_yolov8_pose_openvino_compiled_runtime_precision",
    "resolve_yolov8_pose_openvino_device_name",
    "resolve_yolov8_pose_openvino_port_dtype",
    "resolve_yolov8_pose_openvino_port_name",
    "resolve_yolov8_pose_tensorrt_dtype_name",
    "resolve_yolov8_pose_tensorrt_io_tensor_name",
    "resolve_yolov8_pose_torch_device_name",
]
