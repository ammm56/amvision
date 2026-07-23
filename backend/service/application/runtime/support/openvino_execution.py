"""OpenVINO plugin 配置、编译和 effective 配置读取。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    OpenVinoAutoRuntimeOptions,
    OpenVinoCpuRuntimeOptions,
    OpenVinoGpuRuntimeOptions,
    OpenVinoNpuRuntimeOptions,
)


@dataclass(frozen=True)
class OpenVinoRuntimeDiagnostics:
    """描述 OpenVINO requested/effective 配置和非致命告警。"""

    requested: dict[str, object]
    effective: dict[str, object]
    warnings: tuple[str, ...]


_DIAGNOSTICS_LIMIT = 256
_DIAGNOSTICS_BY_SESSION_ID: OrderedDict[int, OpenVinoRuntimeDiagnostics] = OrderedDict()
_DIAGNOSTICS_LOCK = Lock()


def compile_openvino_model(
    *,
    openvino_module: Any,
    model_path: str,
    device_name: str,
    base_properties: dict[object, object],
    runtime_configuration: DeploymentRuntimeConfiguration,
) -> Any:
    """使用统一 deployment 配置编译 OpenVINO 模型。"""

    core = openvino_module.Core()
    requested_properties = _build_requested_properties(runtime_configuration)
    supported_properties = _read_supported_properties(core, device_name)
    accepted_properties = dict(base_properties)
    warnings: list[str] = []
    for property_name, value in requested_properties.items():
        if supported_properties and property_name not in supported_properties:
            warnings.append(
                f"OpenVINO device {device_name} 不支持 property {property_name}，已忽略"
            )
            continue
        accepted_properties[property_name] = value

    compile_properties = _coerce_compile_property_values(
        openvino_module=openvino_module,
        properties=accepted_properties,
    )
    session = core.compile_model(model_path, device_name, compile_properties)
    effective = _read_effective_properties(
        session,
        tuple(requested_properties),
    )
    _remember_diagnostics(
        session,
        OpenVinoRuntimeDiagnostics(
            requested={
                "backend_options": asdict(runtime_configuration.backend_options),
                "compile_properties": requested_properties,
            },
            effective={
                "device_name": device_name,
                "compile_properties": effective,
            },
            warnings=tuple(warnings),
        ),
    )
    return session


def get_openvino_runtime_diagnostics(
    session: object,
) -> OpenVinoRuntimeDiagnostics | None:
    """读取统一编译入口记录的诊断数据。"""

    with _DIAGNOSTICS_LOCK:
        diagnostics = _DIAGNOSTICS_BY_SESSION_ID.get(id(session))
        if diagnostics is not None:
            _DIAGNOSTICS_BY_SESSION_ID.move_to_end(id(session))
        return diagnostics


def _build_requested_properties(
    configuration: DeploymentRuntimeConfiguration,
) -> dict[str, object]:
    """把强类型 backend_options 转换为 OpenVINO property。"""

    options = configuration.backend_options
    properties: dict[str, object] = {}
    if isinstance(options, OpenVinoCpuRuntimeOptions):
        _set_performance_hint(properties, options.performance_hint)
        _set_auto_value(
            properties, "INFERENCE_NUM_THREADS", options.inference_num_threads
        )
        _set_auto_value(properties, "NUM_STREAMS", options.num_streams)
        _set_auto_value(
            properties,
            "SCHEDULING_CORE_TYPE",
            _map_core_type(options.scheduling_core_type),
        )
        _set_auto_value(
            properties,
            "ENABLE_HYPER_THREADING",
            options.enable_hyper_threading,
        )
        _set_auto_value(properties, "ENABLE_CPU_PINNING", options.enable_cpu_pinning)
    elif isinstance(options, OpenVinoGpuRuntimeOptions):
        _set_performance_hint(properties, options.performance_hint)
        _set_auto_value(properties, "NUM_STREAMS", options.num_streams)
        _set_auto_value(
            properties, "PERFORMANCE_HINT_NUM_REQUESTS", options.num_requests
        )
        _set_auto_value(
            properties,
            "INFERENCE_PRECISION_HINT",
            _map_precision(options.inference_precision),
        )
        _set_auto_value(
            properties, "GPU_QUEUE_PRIORITY", _map_priority(options.queue_priority)
        )
        _set_auto_value(
            properties, "GPU_QUEUE_THROTTLE", _map_priority(options.queue_throttle)
        )
    elif isinstance(options, OpenVinoNpuRuntimeOptions):
        _set_performance_hint(properties, options.performance_hint)
        _set_auto_value(
            properties, "PERFORMANCE_HINT_NUM_REQUESTS", options.num_requests
        )
        _set_auto_value(
            properties,
            "INFERENCE_PRECISION_HINT",
            _map_precision(options.inference_precision),
        )
        _set_auto_value(properties, "NPU_TURBO", options.turbo)
        _set_auto_value(properties, "NPU_TILES", options.tiles)
        if options.compilation_mode_params:
            properties["NPU_COMPILATION_MODE_PARAMS"] = options.compilation_mode_params
    elif isinstance(options, OpenVinoAutoRuntimeOptions):
        _set_performance_hint(properties, options.performance_hint)
        _set_auto_value(
            properties, "PERFORMANCE_HINT_NUM_REQUESTS", options.num_requests
        )
    else:
        raise ValueError("OpenVINO deployment 缺少匹配的 backend_options")
    return properties


def _read_supported_properties(core: object, device_name: str) -> set[str]:
    """读取 device plugin 声明的 property 名称。"""

    try:
        raw_properties = core.get_property(device_name, "SUPPORTED_PROPERTIES")
    except Exception:
        return set()
    return {_normalize_property_name(item) for item in raw_properties}


def _coerce_compile_property_values(
    *,
    openvino_module: Any,
    properties: dict[object, object],
) -> dict[object, object]:
    """把稳定领域值转换为 OpenVINO Python API 要求的强类型 property 值。"""

    compile_properties = dict(properties)
    for property_name, value in compile_properties.items():
        if (
            _normalize_property_name(property_name) != "NUM_STREAMS"
            or isinstance(value, bool)
            or not isinstance(value, int)
        ):
            continue
        streams_namespace = getattr(
            getattr(openvino_module, "properties", None),
            "streams",
            None,
        )
        streams_value_type = getattr(streams_namespace, "Num", None)
        if not callable(streams_value_type):
            raise ServiceConfigurationError(
                "当前 OpenVINO Python runtime 不支持强类型 NUM_STREAMS 配置",
                details={
                    "property_name": "NUM_STREAMS",
                    "property_value": value,
                },
            )
        compile_properties[property_name] = streams_value_type(value)
    return compile_properties


def _read_effective_properties(
    session: object,
    property_names: tuple[str, ...],
) -> dict[str, object]:
    """读取 CompiledModel 实际采用的 property。"""

    effective: dict[str, object] = {}
    for property_name in property_names:
        try:
            value = session.get_property(property_name)
        except Exception:
            continue
        effective[property_name] = _normalize_property_value(value)
    return effective


def _remember_diagnostics(
    session: object, diagnostics: OpenVinoRuntimeDiagnostics
) -> None:
    """在有界进程内注册表中保存 CompiledModel 诊断数据。"""

    with _DIAGNOSTICS_LOCK:
        _DIAGNOSTICS_BY_SESSION_ID[id(session)] = diagnostics
        _DIAGNOSTICS_BY_SESSION_ID.move_to_end(id(session))
        while len(_DIAGNOSTICS_BY_SESSION_ID) > _DIAGNOSTICS_LIMIT:
            _DIAGNOSTICS_BY_SESSION_ID.popitem(last=False)


def _set_performance_hint(properties: dict[str, object], value: str) -> None:
    """设置 performance hint；none 表示不覆盖 plugin。"""

    if value != "none":
        properties["PERFORMANCE_HINT"] = value.upper()


def _set_auto_value(
    properties: dict[str, object],
    property_name: str,
    value: object,
) -> None:
    """只写入显式值。"""

    if value != "auto":
        properties[property_name] = value


def _map_core_type(value: str) -> str:
    return {
        "auto": "auto",
        "any_core": "ANY_CORE",
        "pcore_only": "PCORE_ONLY",
        "ecore_only": "ECORE_ONLY",
    }[value]


def _map_precision(value: str) -> str:
    return {"auto": "auto", "f32": "f32", "f16": "f16"}[value]


def _map_priority(value: str) -> str:
    return value.upper() if value != "auto" else "auto"


def _normalize_property_name(value: object) -> str:
    """把 OpenVINO PropertyName 或字符串转成稳定名称。"""

    text = str(value)
    return text.split(" ", 1)[0].strip()


def _normalize_property_value(value: object) -> object:
    """把 OpenVINO property 值转换为可序列化标量。"""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)
