"""YOLOX runtime 后端加载和输出归一化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolox_core.postprocess import (
    ensure_yolox_prediction_array,
    yolox_prediction_to_numpy_array,
)
from backend.service.application.runtime.support.tensorrt_runtime import (
    prepare_tensorrt_python_runtime,
)


@dataclass(frozen=True)
class YoloXInferenceImports:
    """描述基础推理路径所需的第三方依赖对象。

    字段：
    - cv2：OpenCV 模块。
    - np：NumPy 模块。
    """

    cv2: Any
    np: Any


@dataclass(frozen=True)
class YoloXCudaInferenceImports:
    """描述 TensorRT/CUDA 推理路径所需的第三方依赖对象。

    字段：
    - cv2：OpenCV 模块。
    - np：NumPy 模块。
    - cudart：cuda-python 运行时 API 模块。
    """

    cv2: Any
    np: Any
    cudart: Any


_TENSORRT_LOGGER: Any | None = None
_TENSORRT_LOGGER_SEVERITY: int | None = None


def require_yolox_inference_imports() -> YoloXInferenceImports:
    """按需导入基础推理路径所需依赖。

    返回：
    - YoloXInferenceImports：仅包含 OpenCV 与 NumPy 的依赖集合。
    """

    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 opencv-python 或 numpy 依赖") from error
    return YoloXInferenceImports(cv2=cv2, np=np)


def require_yolox_cuda_inference_imports() -> YoloXCudaInferenceImports:
    """按需导入 TensorRT/CUDA 推理路径所需依赖。

    返回：
    - YoloXCudaInferenceImports：包含 OpenCV、NumPy 与 cuda-python 的依赖集合。
    """

    inference_imports = require_yolox_inference_imports()
    return YoloXCudaInferenceImports(
        cv2=inference_imports.cv2,
        np=inference_imports.np,
        cudart=import_yolox_cuda_runtime_module(),
    )


def import_yolox_cuda_runtime_module() -> Any:
    """导入 cuda-python 的 cudart 模块并在缺失时抛出明确错误。"""

    try:
        from cuda import cudart
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 cuda-python 依赖") from error
    return cudart


def import_yolox_onnxruntime_module() -> Any:
    """导入 ONNXRuntime 模块并在缺失时抛出明确错误。"""

    try:
        import onnxruntime
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 onnxruntime 依赖") from error
    return onnxruntime


def import_yolox_openvino_module() -> Any:
    """导入 OpenVINO 模块并在缺失时抛出明确错误。

    返回：
    - Any：OpenVINO 顶层模块对象。
    """

    try:
        import openvino
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 openvino 依赖") from error
    return openvino


def import_yolox_tensorrt_module() -> Any:
    """导入 TensorRT 模块并在缺失时抛出明确错误。"""

    prepare_tensorrt_python_runtime()
    try:
        import tensorrt
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 tensorrt 依赖") from error
    return tensorrt


def get_yolox_tensorrt_logger(*, tensorrt_module: Any, severity: Any) -> Any:
    """返回进程级复用的 TensorRT logger，避免重复注册 warning。"""

    global _TENSORRT_LOGGER
    global _TENSORRT_LOGGER_SEVERITY
    resolved_severity = int(severity)
    if _TENSORRT_LOGGER is None or _TENSORRT_LOGGER_SEVERITY != resolved_severity:
        _TENSORRT_LOGGER = tensorrt_module.Logger(severity)
        _TENSORRT_LOGGER_SEVERITY = resolved_severity
    return _TENSORRT_LOGGER


def resolve_yolox_onnxruntime_providers(
    *, onnxruntime_module: Any, requested_device_name: str
) -> list[object]:
    """按 device_name 解析 ONNXRuntime provider 列表。"""

    if requested_device_name != "cpu":
        raise InvalidRequestError(
            "当前 onnxruntime runtime session 仅支持 cpu device_name",
            details={"device_name": requested_device_name},
        )
    available_providers = set(onnxruntime_module.get_available_providers())
    if "CPUExecutionProvider" not in available_providers:
        raise ServiceConfigurationError(
            "当前运行环境缺少 CPUExecutionProvider，无法执行 onnxruntime 推理",
            details={"available_providers": sorted(available_providers)},
        )
    return ["CPUExecutionProvider"]


def resolve_yolox_openvino_device_name(*, requested_device_name: str) -> str:
    """按 device_name 解析 OpenVINO 设备选择串。

    参数：
    - requested_device_name：运行时快照中的 device 名称。

    返回：
    - str：OpenVINO compile_model 使用的设备字符串。
    """

    device_name_map = {
        "auto": "AUTO",
        "cpu": "CPU",
        "gpu": "GPU",
        "npu": "NPU",
    }
    resolved = device_name_map.get(requested_device_name)
    if resolved is None:
        raise InvalidRequestError(
            "当前 openvino runtime session 仅支持 auto、cpu、gpu 或 npu device_name",
            details={"device_name": requested_device_name},
        )
    return resolved


def build_yolox_openvino_compile_properties(
    *,
    openvino_module: Any,
    runtime_precision: str,
    requested_device_name: str,
) -> dict[object, object]:
    """按 runtime precision 构造 OpenVINO compile_model 属性。"""

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


def resolve_yolox_openvino_compiled_runtime_precision(*, session: Any, fallback_precision: str) -> str:
    """读取 OpenVINO 编译后实际采用的 runtime precision。"""

    try:
        resolved = session.get_property("INFERENCE_PRECISION_HINT")
    except Exception:
        return fallback_precision
    normalized = normalize_yolox_openvino_type_name(resolved)
    precision_map = {
        "float16": "fp16",
        "float32": "fp32",
    }
    return precision_map.get(normalized, fallback_precision)


def resolve_yolox_openvino_port_dtype(port: Any, *, fallback: str) -> str:
    """读取 OpenVINO 端口实际张量 dtype。"""

    element_type_getter = getattr(port, "get_element_type", None)
    if not callable(element_type_getter):
        return fallback
    try:
        return normalize_yolox_openvino_type_name(element_type_getter()) or fallback
    except Exception:
        return fallback


def normalize_yolox_openvino_type_name(value: object) -> str:
    """把 OpenVINO 类型对象归一化为稳定字符串。"""

    normalized = str(value).strip().lower()
    if normalized.startswith("<type: '") and normalized.endswith("'>"):
        normalized = normalized[len("<type: '") : -2]
    type_name_map = {
        "f16": "float16",
        "f32": "float32",
    }
    return type_name_map.get(normalized, normalized)


def resolve_yolox_openvino_port_name(port: Any, *, fallback: str) -> str:
    """从 OpenVINO 端口对象提取稳定名称。

    参数：
    - port：OpenVINO 输入或输出端口对象。
    - fallback：端口未暴露名称时使用的回退值。

    返回：
    - str：端口名称或回退值。
    """

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


def resolve_yolox_tensorrt_io_tensor_name(
    *, engine: Any, tensorrt_module: Any, io_mode: Any, fallback: str
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


def normalize_yolox_tensor_shape(shape: object) -> tuple[int, ...]:
    """把后端返回的 shape 对象归一化为整数元组。"""

    try:
        return tuple(int(dim) for dim in shape)
    except TypeError:
        return ()


def resolve_yolox_tensorrt_dtype_name(
    *, tensorrt_module: Any, tensor_dtype: Any, fallback: str
) -> str:
    """把 TensorRT dtype 对象归一化为稳定字符串。"""

    normalized_name_map = {
        str(tensorrt_module.float32).strip().lower(): "float32",
        str(tensorrt_module.float16).strip().lower(): "float16",
        str(tensorrt_module.int32).strip().lower(): "int32",
    }
    normalized = str(tensor_dtype).strip().lower()
    return normalized_name_map.get(normalized, fallback)


def resolve_yolox_cuda_device_index(device_name: str) -> int:
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


def resolve_yolox_cuda_runtime_device_name(*, cudart_module: Any, requested_device_name: str) -> str:
    """在不依赖 torch 的前提下校验并返回 CUDA device 名称。"""

    device_name = requested_device_name.strip().lower() if requested_device_name.strip() else "cuda:0"
    if device_name == "cuda":
        device_name = "cuda:0"
    if not device_name.startswith("cuda:"):
        raise InvalidRequestError(
            "device_name 必须是 cuda 或 cuda:<index>",
            details={"device_name": requested_device_name},
        )
    device_index = resolve_yolox_cuda_device_index(device_name)
    cuda_status, available_device_count = cudart_module.cudaGetDeviceCount()
    if int(cuda_status) != 0:
        raise ServiceConfigurationError(
            "当前运行环境无法读取 CUDA device 列表",
            details={"device_name": device_name, "status_code": int(cuda_status), "status_name": cuda_status.name},
        )
    if int(available_device_count) <= 0:
        raise InvalidRequestError(
            "当前运行环境没有可用 GPU，不能使用 CUDA 预测",
            details={"device_name": device_name},
        )
    if device_index >= int(available_device_count):
        raise InvalidRequestError(
            "指定的 CUDA device 超出了本机可用 GPU 范围",
            details={"device_name": device_name, "available_gpu_count": int(available_device_count)},
        )
    return device_name


def ensure_yolox_cuda_success(
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


def release_yolox_cuda_resource(result: object) -> None:
    """释放 CUDA 资源时吞掉次级清理错误，避免覆盖主错误。"""

    if not isinstance(result, tuple) or not result:
        return
    status = result[0]
    if int(status) != 0:
        return


def normalize_yolox_onnxruntime_outputs(*, outputs: Any, imports: Any) -> Any:
    """把 ONNXRuntime 输出转换为统一的预测数组。

    参数：
    - outputs：ONNXRuntime 原始输出列表。
    - imports：基础推理依赖集合。

    返回：
    - Any：形状为 batch x boxes x channels 的 NumPy 数组。
    """

    if not isinstance(outputs, list) or not outputs:
        raise InvalidRequestError("onnxruntime 推理输出为空")
    return ensure_yolox_prediction_array(
        prediction_value=outputs[0],
        np_module=imports.np,
        backend_name="onnxruntime",
    )


def normalize_yolox_openvino_outputs(
    *,
    outputs: Any,
    output_port: Any,
    output_name: str,
    imports: Any,
) -> Any:
    """把 OpenVINO 输出转换为统一的预测数组。

    参数：
    - outputs：OpenVINO infer_new_request 返回的输出字典。
    - output_port：主输出端口对象。
    - output_name：主输出端口名称。
    - imports：基础推理依赖集合。

    返回：
    - Any：形状为 batch x boxes x channels 的 NumPy 数组。
    """

    raw_output = None
    for output_key in (output_port, output_name):
        try:
            raw_output = outputs[output_key]
            break
        except Exception:
            continue
    if raw_output is None and hasattr(outputs, "values"):
        output_values = tuple(outputs.values())
        if output_values:
            raw_output = output_values[0]
    if raw_output is None:
        raise InvalidRequestError("openvino 推理输出为空")
    return ensure_yolox_prediction_array(
        prediction_value=raw_output,
        np_module=imports.np,
        backend_name="openvino",
    )


def normalize_yolox_tensorrt_outputs(*, output_array: Any, imports: YoloXCudaInferenceImports) -> Any:
    """把 TensorRT 输出张量转换为统一的预测数组。"""

    return ensure_yolox_prediction_array(
        prediction_value=yolox_prediction_to_numpy_array(
            prediction_tensor=output_array,
            np_module=imports.np,
        ),
        np_module=imports.np,
        backend_name="tensorrt",
    )
