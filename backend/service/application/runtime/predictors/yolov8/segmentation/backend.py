"""YOLOv8 segmentation runtime 后端依赖和输出归一化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolov8_core.inference import (
    normalize_yolov8_segmentation_inference_outputs,
)
from backend.service.application.runtime.support.tensorrt_runtime import (
    prepare_tensorrt_python_runtime,
)


@dataclass(frozen=True)
class YoloV8SegmentationInferenceImports:
    """描述 YOLOv8 segmentation 基础推理依赖。"""

    cv2: Any
    np: Any


@dataclass(frozen=True)
class YoloV8SegmentationPytorchInferenceImports(YoloV8SegmentationInferenceImports):
    """描述 YOLOv8 segmentation PyTorch 推理依赖。"""

    torch: Any


@dataclass(frozen=True)
class YoloV8SegmentationCudaInferenceImports(YoloV8SegmentationInferenceImports):
    """描述 YOLOv8 segmentation TensorRT/CUDA 推理依赖。"""

    cudart: Any


def require_yolov8_segmentation_inference_imports() -> YoloV8SegmentationInferenceImports:
    """按需导入基础推理依赖。"""

    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 opencv-python 或 numpy 依赖") from error
    return YoloV8SegmentationInferenceImports(cv2=cv2, np=np)


def require_yolov8_segmentation_pytorch_imports() -> YoloV8SegmentationPytorchInferenceImports:
    """按需导入 PyTorch 推理依赖。"""

    inference_imports = require_yolov8_segmentation_inference_imports()
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 torch 依赖") from error
    return YoloV8SegmentationPytorchInferenceImports(
        cv2=inference_imports.cv2,
        np=inference_imports.np,
        torch=torch,
    )


def require_yolov8_segmentation_cuda_imports() -> YoloV8SegmentationCudaInferenceImports:
    """按需导入 TensorRT/CUDA 推理依赖。"""

    inference_imports = require_yolov8_segmentation_inference_imports()
    return YoloV8SegmentationCudaInferenceImports(
        cv2=inference_imports.cv2,
        np=inference_imports.np,
        cudart=import_yolov8_segmentation_cuda_runtime_module(),
    )


def import_yolov8_segmentation_cuda_runtime_module() -> Any:
    """导入 cuda-python 的 cudart 模块并在缺失时抛出明确错误。"""

    try:
        from cuda import cudart
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 cuda-python 依赖") from error
    return cudart


def import_yolov8_segmentation_onnxruntime_module() -> Any:
    """导入 ONNXRuntime 模块并在缺失时抛出明确错误。"""

    try:
        import onnxruntime
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 onnxruntime 依赖") from error
    return onnxruntime


def import_yolov8_segmentation_openvino_module() -> Any:
    """导入 OpenVINO 模块并在缺失时抛出明确错误。"""

    try:
        import openvino
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 openvino 依赖") from error
    return openvino


def import_yolov8_segmentation_tensorrt_module() -> Any:
    """导入 TensorRT 模块并在缺失时抛出明确错误。"""

    prepare_tensorrt_python_runtime()
    try:
        import tensorrt
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 tensorrt 依赖") from error
    return tensorrt


def resolve_yolov8_segmentation_onnxruntime_providers(
    *,
    onnxruntime_module: Any,
    requested_device_name: str,
) -> list[object]:
    """按 device_name 解析 YOLOv8 segmentation ONNXRuntime provider。"""

    if requested_device_name != "cpu":
        raise InvalidRequestError(
            "当前 YOLOv8 segmentation onnxruntime session 仅支持 cpu device_name",
            details={"device_name": requested_device_name},
        )
    available_providers = set(onnxruntime_module.get_available_providers())
    if "CPUExecutionProvider" not in available_providers:
        raise ServiceConfigurationError(
            "当前运行环境缺少 CPUExecutionProvider，无法执行 onnxruntime 推理",
            details={"available_providers": sorted(available_providers)},
        )
    return ["CPUExecutionProvider"]


def resolve_yolov8_segmentation_openvino_device_name(*, requested_device_name: str) -> str:
    """按 device_name 解析 YOLOv8 segmentation OpenVINO 设备选择串。"""

    device_name_map = {
        "auto": "AUTO",
        "cpu": "CPU",
        "gpu": "GPU",
        "npu": "NPU",
    }
    resolved = device_name_map.get(requested_device_name)
    if resolved is None:
        raise InvalidRequestError(
            "当前 YOLOv8 segmentation openvino session 仅支持 auto、cpu、gpu 或 npu device_name",
            details={"device_name": requested_device_name},
        )
    return resolved


def build_yolov8_segmentation_openvino_compile_properties(
    *,
    openvino_module: Any,
    runtime_precision: str,
    requested_device_name: str,
) -> dict[object, object]:
    """按 runtime precision 构造 YOLOv8 segmentation OpenVINO compile_model 属性。"""

    if runtime_precision == "fp32":
        return {}
    if runtime_precision == "fp16" and requested_device_name in {"gpu", "npu"}:
        return {openvino_module.properties.hint.inference_precision: openvino_module.Type.f16}
    raise InvalidRequestError(
        "openvino fp16 仅支持 gpu 或 npu device_name；auto/cpu 仍要求 fp32",
        details={
            "runtime_backend": "openvino",
            "runtime_precision": runtime_precision,
            "device_name": requested_device_name,
        },
    )


def normalize_yolov8_segmentation_openvino_type_name(value: object) -> str:
    """把 OpenVINO 类型对象归一化为稳定字符串。"""

    normalized = str(value).strip().lower()
    if normalized.startswith("<type: '") and normalized.endswith("'>"):
        normalized = normalized[len("<type: '") : -2]
    type_name_map = {
        "f16": "float16",
        "f32": "float32",
    }
    return type_name_map.get(normalized, normalized)


def resolve_yolov8_segmentation_openvino_compiled_runtime_precision(
    *,
    session: Any,
    fallback_precision: str,
) -> str:
    """读取 OpenVINO 编译后实际采用的 runtime precision。"""

    try:
        resolved = session.get_property("INFERENCE_PRECISION_HINT")
    except Exception:
        return fallback_precision
    normalized = normalize_yolov8_segmentation_openvino_type_name(resolved)
    precision_map = {
        "float16": "fp16",
        "float32": "fp32",
    }
    return precision_map.get(normalized, fallback_precision)


def resolve_yolov8_segmentation_openvino_port_dtype(port: Any, *, fallback: str) -> str:
    """读取 OpenVINO 端口实际张量 dtype。"""

    element_type_getter = getattr(port, "get_element_type", None)
    if not callable(element_type_getter):
        return fallback
    try:
        return normalize_yolov8_segmentation_openvino_type_name(element_type_getter()) or fallback
    except Exception:
        return fallback


def resolve_yolov8_segmentation_openvino_port_name(port: Any, *, fallback: str) -> str:
    """从 OpenVINO 端口对象提取稳定名称。"""

    for attribute_name in ("get_any_name", "any_name"):
        resolver = getattr(port, attribute_name, None)
        if resolver is None:
            continue
        try:
            resolved_name = resolver() if callable(resolver) else resolver
        except Exception:
            continue
        normalized_name = str(resolved_name).strip()
        if normalized_name:
            return normalized_name
    names_getter = getattr(port, "get_names", None)
    if callable(names_getter):
        try:
            resolved_names = tuple(
                sorted(str(item).strip() for item in names_getter() if str(item).strip())
            )
        except Exception:
            resolved_names = ()
        if resolved_names:
            return resolved_names[0]
    return fallback


_TENSORRT_LOGGER: Any | None = None
_TENSORRT_LOGGER_SEVERITY: int | None = None


def get_yolov8_segmentation_tensorrt_logger(*, tensorrt_module: Any, severity: Any) -> Any:
    """返回进程级复用的 YOLOv8 segmentation TensorRT logger。"""

    global _TENSORRT_LOGGER
    global _TENSORRT_LOGGER_SEVERITY
    resolved_severity = int(severity)
    if _TENSORRT_LOGGER is None or _TENSORRT_LOGGER_SEVERITY != resolved_severity:
        _TENSORRT_LOGGER = tensorrt_module.Logger(severity)
        _TENSORRT_LOGGER_SEVERITY = resolved_severity
    return _TENSORRT_LOGGER


def resolve_yolov8_segmentation_tensorrt_io_tensor_name(
    *,
    engine: Any,
    tensorrt_module: Any,
    io_mode: Any,
    fallback: str,
) -> str:
    """返回 TensorRT engine 中首个匹配 I/O 类型的张量名称。"""

    for tensor_index in range(int(engine.num_io_tensors)):
        tensor_name = str(engine.get_tensor_name(tensor_index))
        if engine.get_tensor_mode(tensor_name) == io_mode:
            return tensor_name
    raise ServiceConfigurationError(
        "TensorRT engine 缺少期望的 I/O 张量",
        details={
            "io_mode": "input" if io_mode == tensorrt_module.TensorIOMode.INPUT else "output",
            "fallback": fallback,
        },
    )


def list_yolov8_segmentation_tensorrt_output_names(
    *,
    engine: Any,
    tensorrt_module: Any,
) -> list[str]:
    """列出 TensorRT engine 的所有输出张量名称。"""

    names: list[str] = []
    for index in range(int(engine.num_io_tensors)):
        name = str(engine.get_tensor_name(index))
        if engine.get_tensor_mode(name) == tensorrt_module.TensorIOMode.OUTPUT:
            names.append(name)
    return names


def normalize_yolov8_segmentation_tensor_shape(shape: object) -> tuple[int, ...]:
    """把后端返回的 shape 对象归一化为整数元组。"""

    try:
        return tuple(int(dim) for dim in shape)
    except TypeError:
        return ()


def resolve_yolov8_segmentation_tensorrt_dtype_name(
    *,
    tensorrt_module: Any,
    tensor_dtype: Any,
    fallback: str,
) -> str:
    """把 TensorRT dtype 对象归一化为稳定字符串。"""

    normalized_name_map = {
        str(tensorrt_module.float32).strip().lower(): "float32",
        str(tensorrt_module.float16).strip().lower(): "float16",
        str(tensorrt_module.int32).strip().lower(): "int32",
    }
    normalized = str(tensor_dtype).strip().lower()
    return normalized_name_map.get(normalized, fallback)


def resolve_yolov8_segmentation_cuda_device_index(device_name: str) -> int:
    """把 cuda:<index> 设备名解析为整数索引。"""

    if device_name == "cuda":
        return 0
    if device_name.startswith("cuda:"):
        raw_index = device_name.split(":", 1)[1]
        if raw_index.isdigit():
            return int(raw_index)
    raise InvalidRequestError(
        "device_name 必须是 cuda 或 cuda:<index>",
        details={"device_name": device_name},
    )


def resolve_yolov8_segmentation_cuda_runtime_device_name(
    *,
    cudart_module: Any,
    requested_device_name: str,
) -> str:
    """在不依赖 torch 的前提下校验并返回 CUDA device 名称。"""

    device_name = requested_device_name.strip().lower() if requested_device_name.strip() else "cuda:0"
    if device_name == "cuda":
        device_name = "cuda:0"
    if not device_name.startswith("cuda:"):
        raise InvalidRequestError(
            "device_name 必须是 cuda 或 cuda:<index>",
            details={"device_name": requested_device_name},
        )
    device_index = resolve_yolov8_segmentation_cuda_device_index(device_name)
    cuda_status, available_device_count = cudart_module.cudaGetDeviceCount()
    if int(cuda_status) != 0:
        raise ServiceConfigurationError(
            "当前运行环境无法读取 CUDA device 列表",
            details={
                "device_name": device_name,
                "status_code": int(cuda_status),
                "status_name": getattr(cuda_status, "name", str(cuda_status)),
            },
        )
    if int(available_device_count) <= 0:
        raise InvalidRequestError(
            "当前运行环境没有可用 GPU，不能使用 CUDA 预测",
            details={"device_name": device_name},
        )
    if device_index >= int(available_device_count):
        raise InvalidRequestError(
            "指定的 CUDA device 超出了本机可用 GPU 范围",
            details={
                "device_name": device_name,
                "available_gpu_count": int(available_device_count),
            },
        )
    return device_name


def ensure_yolov8_segmentation_cuda_success(
    result: object,
    *,
    operation_name: str,
    details: dict[str, object] | None = None,
) -> tuple[object, ...]:
    """校验 cuda-python API 返回值，并在失败时抛出明确错误。"""

    if not isinstance(result, tuple) or not result:
        raise ServiceConfigurationError(
            f"{operation_name} 返回值格式不合法",
            details={"result_repr": repr(result), **dict(details or {})},
        )
    status = result[0]
    if int(status) != 0:
        raise ServiceConfigurationError(
            f"{operation_name} 失败",
            details={
                "status_code": int(status),
                "status_name": getattr(status, "name", str(status)),
                **dict(details or {}),
            },
        )
    return tuple(result[1:])


def release_yolov8_segmentation_cuda_resource(result: object) -> None:
    """释放 CUDA 资源时吞掉次级清理错误，避免覆盖主错误。"""

    if not isinstance(result, tuple) or not result:
        return
    status = result[0]
    if int(status) != 0:
        return


def resolve_yolov8_segmentation_torch_device_name(
    *,
    torch_module: Any,
    requested_device_name: str,
) -> str:
    """解析 YOLOv8 segmentation PyTorch 推理 device。"""

    if requested_device_name == "cpu":
        return "cpu"
    if requested_device_name == "cuda":
        requested_device_name = "cuda:0"
    if requested_device_name.startswith("cuda:"):
        if not torch_module.cuda.is_available():
            raise InvalidRequestError(
                "当前环境没有可用 CUDA device",
                details={"device_name": requested_device_name},
            )
        raw_index = requested_device_name.split(":", 1)[1]
        if not raw_index.isdigit():
            raise InvalidRequestError(
                "device_name 必须是 cpu、cuda 或 cuda:<index>",
                details={"device_name": requested_device_name},
            )
        device_index = int(raw_index)
        available_count = int(torch_module.cuda.device_count())
        if device_index >= available_count:
            raise InvalidRequestError(
                "请求的 CUDA device 不存在",
                details={
                    "device_name": requested_device_name,
                    "available_gpu_count": available_count,
                },
            )
        return requested_device_name
    raise InvalidRequestError(
        "device_name 必须是 cpu、cuda 或 cuda:<index>",
        details={"device_name": requested_device_name},
    )


def enable_yolov8_segmentation_cuda_fast_path(*, torch_module: Any, device_name: str) -> None:
    """按需打开 YOLOv8 segmentation CUDA 推理常用加速设置。"""

    if not device_name.startswith("cuda"):
        return
    cudnn_module = getattr(torch_module.backends, "cudnn", None)
    if cudnn_module is not None:
        cudnn_module.benchmark = True
    if hasattr(torch_module, "set_float32_matmul_precision"):
        torch_module.set_float32_matmul_precision("high")


def normalize_yolov8_segmentation_outputs_for_backend(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any]:
    """把后端输出统一转换为 YOLOv8 segmentation prediction/proto。"""

    return normalize_yolov8_segmentation_inference_outputs(
        outputs=outputs,
        np_module=np_module,
    )


__all__ = [
    "YoloV8SegmentationCudaInferenceImports",
    "YoloV8SegmentationInferenceImports",
    "YoloV8SegmentationPytorchInferenceImports",
    "build_yolov8_segmentation_openvino_compile_properties",
    "enable_yolov8_segmentation_cuda_fast_path",
    "ensure_yolov8_segmentation_cuda_success",
    "get_yolov8_segmentation_tensorrt_logger",
    "import_yolov8_segmentation_cuda_runtime_module",
    "import_yolov8_segmentation_onnxruntime_module",
    "import_yolov8_segmentation_openvino_module",
    "import_yolov8_segmentation_tensorrt_module",
    "list_yolov8_segmentation_tensorrt_output_names",
    "normalize_yolov8_segmentation_openvino_type_name",
    "normalize_yolov8_segmentation_outputs_for_backend",
    "normalize_yolov8_segmentation_tensor_shape",
    "release_yolov8_segmentation_cuda_resource",
    "require_yolov8_segmentation_cuda_imports",
    "require_yolov8_segmentation_inference_imports",
    "require_yolov8_segmentation_pytorch_imports",
    "resolve_yolov8_segmentation_cuda_device_index",
    "resolve_yolov8_segmentation_cuda_runtime_device_name",
    "resolve_yolov8_segmentation_onnxruntime_providers",
    "resolve_yolov8_segmentation_openvino_compiled_runtime_precision",
    "resolve_yolov8_segmentation_openvino_device_name",
    "resolve_yolov8_segmentation_openvino_port_dtype",
    "resolve_yolov8_segmentation_openvino_port_name",
    "resolve_yolov8_segmentation_tensorrt_dtype_name",
    "resolve_yolov8_segmentation_tensorrt_io_tensor_name",
    "resolve_yolov8_segmentation_torch_device_name",
]
