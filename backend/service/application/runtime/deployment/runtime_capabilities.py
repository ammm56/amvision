"""模型部署运行时能力探测。"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from importlib import import_module, util
import os

from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    OpenVinoCpuRuntimeOptions,
    build_default_runtime_configuration,
    serialize_deployment_runtime_configuration,
)


_OPENVINO_FIELD_PROPERTIES = {
    "performance_hint": "PERFORMANCE_HINT",
    "inference_num_threads": "INFERENCE_NUM_THREADS",
    "num_streams": "NUM_STREAMS",
    "scheduling_core_type": "SCHEDULING_CORE_TYPE",
    "enable_hyper_threading": "ENABLE_HYPER_THREADING",
    "enable_cpu_pinning": "ENABLE_CPU_PINNING",
    "num_requests": "PERFORMANCE_HINT_NUM_REQUESTS",
    "inference_precision": "INFERENCE_PRECISION_HINT",
    "queue_priority": "GPU_QUEUE_PRIORITY",
    "queue_throttle": "GPU_QUEUE_THROTTLE",
    "turbo": "NPU_TURBO",
    "tiles": "NPU_TILES",
    "compilation_mode_params": "NPU_COMPILATION_MODE_PARAMS",
}


def build_host_default_runtime_configuration(
    *,
    runtime_backend: str,
    device_name: str,
) -> DeploymentRuntimeConfiguration:
    """按当前主机能力构建 deployment 默认配置。"""

    configuration = build_default_runtime_configuration(
        runtime_backend=runtime_backend,
        device_name=device_name,
    )
    options = configuration.backend_options
    if isinstance(options, OpenVinoCpuRuntimeOptions):
        physical_core_count = int(
            _read_cpu_hardware_summary()["cpu_physical_core_count"]
        )
        return replace(
            configuration,
            backend_options=replace(
                options,
                inference_num_threads=max(1, physical_core_count),
            ),
        )
    return configuration


def evaluate_runtime_configuration_warnings(
    configuration: DeploymentRuntimeConfiguration,
) -> tuple[str, ...]:
    """返回硬件预算相关的非阻断告警。"""

    options = configuration.backend_options
    if not isinstance(options, OpenVinoCpuRuntimeOptions):
        return ()
    thread_count = options.inference_num_threads
    if not isinstance(thread_count, int):
        return ()
    physical_core_count = int(_read_cpu_hardware_summary()["cpu_physical_core_count"])
    requested_thread_count = configuration.instance_count * thread_count
    if requested_thread_count <= physical_core_count:
        return ()
    return (
        "OpenVINO CPU session 的线程预算总和 "
        f"{requested_thread_count} 超过当前主机物理核心数 {physical_core_count}；"
        "允许启动，但并发推理可能因 CPU 过度订阅而变慢",
    )


def read_cpu_hardware_summary() -> dict[str, object]:
    """返回当前进程启动后稳定使用的 CPU 硬件摘要。"""

    return dict(_read_cpu_hardware_summary())


def inspect_deployment_runtime_capabilities(
    *,
    runtime_backend: str,
    device_name: str,
) -> dict[str, object]:
    """探测指定 backend/device 的当前机器能力。"""

    backend = runtime_backend.strip().lower()
    device = device_name.strip().lower()
    hardware = _read_cpu_hardware_summary()
    default_configuration = serialize_deployment_runtime_configuration(
        build_host_default_runtime_configuration(
            runtime_backend=backend,
            device_name=device,
        )
    )
    if backend == "openvino":
        return _inspect_openvino_capabilities(
            device_name=device,
            hardware=hardware,
            default_configuration=default_configuration,
        )
    if backend == "tensorrt":
        available = util.find_spec("tensorrt") is not None
        return {
            "runtime_backend": backend,
            "device_name": device,
            "available": available,
            "hardware": hardware,
            "supported_backend_fields": [
                "optimization_profile_index",
                "pinned_output_buffer_enabled",
                "pinned_output_buffer_max_bytes",
            ],
            "read_only_properties": {},
            "default_runtime_configuration": default_configuration,
            "warnings": [] if available else ["当前 Python runtime 未安装 TensorRT"],
        }
    return {
        "runtime_backend": backend,
        "device_name": device,
        "available": True,
        "hardware": hardware,
        "supported_backend_fields": [],
        "read_only_properties": {},
        "default_runtime_configuration": default_configuration,
        "warnings": [],
    }


def _inspect_openvino_capabilities(
    *,
    device_name: str,
    hardware: dict[str, object],
    default_configuration: dict[str, object],
) -> dict[str, object]:
    """探测 OpenVINO plugin 能力。"""

    if util.find_spec("openvino") is None:
        return {
            "runtime_backend": "openvino",
            "device_name": device_name,
            "available": False,
            "hardware": hardware,
            "supported_backend_fields": [],
            "read_only_properties": {},
            "default_runtime_configuration": default_configuration,
            "warnings": ["当前 Python runtime 未安装 OpenVINO"],
        }
    try:
        openvino_module = import_module("openvino")
        core = openvino_module.Core()
        compiled_device_name = _normalize_openvino_device_name(device_name)
        available_devices = tuple(str(item) for item in core.available_devices)
        raw_supported = core.get_property(
            compiled_device_name,
            "SUPPORTED_PROPERTIES",
        )
        supported_properties = {str(item).split(" ", 1)[0] for item in raw_supported}
        fields = [
            field_name
            for field_name, property_name in _OPENVINO_FIELD_PROPERTIES.items()
            if property_name in supported_properties
        ]
        read_only_properties: dict[str, object] = {
            "supported_properties": sorted(supported_properties),
        }
        if compiled_device_name.startswith("NPU"):
            max_tiles = _read_positive_openvino_property(
                core,
                compiled_device_name,
                "NPU_MAX_TILES",
            )
            if max_tiles is not None:
                read_only_properties["npu_max_tiles"] = max_tiles
        return {
            "runtime_backend": "openvino",
            "device_name": device_name,
            "available": _is_openvino_device_available(
                compiled_device_name,
                available_devices,
            ),
            "hardware": {
                **hardware,
                "openvino_available_devices": list(available_devices),
            },
            "supported_backend_fields": fields,
            "read_only_properties": read_only_properties,
            "default_runtime_configuration": default_configuration,
            "warnings": [],
        }
    except Exception as error:
        return {
            "runtime_backend": "openvino",
            "device_name": device_name,
            "available": False,
            "hardware": hardware,
            "supported_backend_fields": [],
            "read_only_properties": {},
            "default_runtime_configuration": default_configuration,
            "warnings": [f"OpenVINO capability 探测失败: {error}"],
        }


@lru_cache(maxsize=1)
def _read_cpu_hardware_summary() -> dict[str, object]:
    """读取 CPU 物理核心和逻辑处理器数量。"""

    logical_count = int(os.cpu_count() or 1)
    physical_count = logical_count
    if util.find_spec("psutil") is not None:
        try:
            psutil_module = import_module("psutil")
            physical_count = int(psutil_module.cpu_count(logical=False) or logical_count)
        except Exception:
            physical_count = logical_count
    return {
        "cpu_physical_core_count": physical_count,
        "cpu_logical_processor_count": logical_count,
    }


def _normalize_openvino_device_name(device_name: str) -> str:
    """转换为 OpenVINO Core 接受的 device 名称。"""

    normalized = device_name.strip().upper()
    return normalized or "AUTO"


def _is_openvino_device_available(
    compiled_device_name: str,
    available_devices: tuple[str, ...],
) -> bool:
    """判断显式 plugin 或 AUTO 是否可用。"""

    if compiled_device_name.startswith("AUTO") or compiled_device_name.startswith("MULTI"):
        return bool(available_devices)
    base_device = compiled_device_name.split(".", 1)[0]
    return any(item.split(".", 1)[0].upper() == base_device for item in available_devices)


def _read_positive_openvino_property(
    core: object,
    device_name: str,
    property_name: str,
) -> int | None:
    """读取可选的 OpenVINO 正整数只读属性。"""

    try:
        value = int(core.get_property(device_name, property_name))
    except (TypeError, ValueError, RuntimeError):
        return None
    return value if value > 0 else None
