"""模型部署运行时配置领域对象。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, TypeAlias


AutoInt: TypeAlias = int | Literal["auto"]
AutoBool: TypeAlias = bool | Literal["auto"]
AutoString: TypeAlias = str | Literal["auto"]


@dataclass(frozen=True)
class DeploymentExecutionPolicy:
    """描述与推理后端无关的平台执行策略。"""

    instance_count: int = 1
    isolation_level: Literal["session"] = "session"
    overflow_policy: Literal["reject"] = "reject"
    performance_goal: Literal["latency", "throughput", "balanced"] = "latency"


@dataclass(frozen=True)
class DeploymentLifecycleOptions:
    """描述 deployment 进程的预热与保温策略。"""

    warmup_dummy_inference_count: int | None = None
    warmup_dummy_image_size: tuple[int, int] | None = None
    keep_warm_enabled: bool | None = None
    keep_warm_interval_seconds: float | None = None


@dataclass(frozen=True)
class DefaultRuntimeOptions:
    """描述没有专属运行时控制项的 backend。"""

    kind: Literal["default"] = "default"


@dataclass(frozen=True)
class OpenVinoCpuRuntimeOptions:
    """描述 OpenVINO CPU plugin 的部署配置。"""

    kind: Literal["openvino-cpu"] = "openvino-cpu"
    performance_hint: Literal[
        "latency", "throughput", "cumulative_throughput", "none"
    ] = "latency"
    inference_num_threads: AutoInt = "auto"
    num_streams: AutoInt = 1
    scheduling_core_type: Literal["auto", "any_core", "pcore_only", "ecore_only"] = (
        "auto"
    )
    enable_hyper_threading: AutoBool = "auto"
    enable_cpu_pinning: AutoBool = "auto"


@dataclass(frozen=True)
class OpenVinoGpuRuntimeOptions:
    """描述 OpenVINO GPU plugin 的部署配置。"""

    kind: Literal["openvino-gpu"] = "openvino-gpu"
    performance_hint: Literal[
        "latency", "throughput", "cumulative_throughput", "none"
    ] = "latency"
    num_streams: AutoInt = 1
    num_requests: AutoInt = "auto"
    inference_precision: Literal["auto", "f32", "f16"] = "auto"
    queue_priority: Literal["auto", "low", "medium", "high"] = "auto"
    queue_throttle: Literal["auto", "low", "medium", "high"] = "auto"


@dataclass(frozen=True)
class OpenVinoNpuRuntimeOptions:
    """描述 OpenVINO NPU plugin 的部署配置。"""

    kind: Literal["openvino-npu"] = "openvino-npu"
    performance_hint: Literal[
        "latency", "throughput", "cumulative_throughput", "none"
    ] = "latency"
    num_requests: AutoInt = "auto"
    inference_precision: Literal["auto", "f16"] = "auto"
    turbo: AutoBool = "auto"
    tiles: AutoInt = "auto"
    compilation_mode_params: str | None = None


@dataclass(frozen=True)
class OpenVinoAutoRuntimeOptions:
    """描述 OpenVINO AUTO/MULTI 设备选择配置。"""

    kind: Literal["openvino-auto"] = "openvino-auto"
    performance_hint: Literal[
        "latency", "throughput", "cumulative_throughput", "none"
    ] = "latency"
    num_requests: AutoInt = "auto"


@dataclass(frozen=True)
class TensorRtRuntimeOptions:
    """描述 TensorRT engine 加载后的运行时配置。"""

    kind: Literal["tensorrt"] = "tensorrt"
    optimization_profile_index: int = 0
    pinned_output_buffer_enabled: bool | None = None
    pinned_output_buffer_max_bytes: int | None = None


BackendRuntimeOptions: TypeAlias = (
    DefaultRuntimeOptions
    | OpenVinoCpuRuntimeOptions
    | OpenVinoGpuRuntimeOptions
    | OpenVinoNpuRuntimeOptions
    | OpenVinoAutoRuntimeOptions
    | TensorRtRuntimeOptions
)


@dataclass(frozen=True)
class DeploymentRuntimeConfiguration:
    """描述一个 DeploymentInstance 的完整运行时配置。"""

    execution: DeploymentExecutionPolicy = field(
        default_factory=DeploymentExecutionPolicy
    )
    lifecycle: DeploymentLifecycleOptions = field(
        default_factory=DeploymentLifecycleOptions
    )
    backend_options: BackendRuntimeOptions = field(
        default_factory=DefaultRuntimeOptions
    )

    @property
    def instance_count(self) -> int:
        """返回平台实例数。"""

        return self.execution.instance_count


def build_default_runtime_configuration(
    *,
    runtime_backend: str,
    device_name: str,
) -> DeploymentRuntimeConfiguration:
    """按已解析的 backend 和 device 构建明确的默认配置。"""

    normalized_backend = runtime_backend.strip().lower()
    normalized_device = device_name.strip().lower()
    if normalized_backend == "openvino":
        if normalized_device.startswith("cpu"):
            options: BackendRuntimeOptions = OpenVinoCpuRuntimeOptions()
        elif normalized_device.startswith("gpu"):
            options = OpenVinoGpuRuntimeOptions()
        elif normalized_device.startswith("npu"):
            options = OpenVinoNpuRuntimeOptions()
        else:
            options = OpenVinoAutoRuntimeOptions()
    elif normalized_backend == "tensorrt":
        options = TensorRtRuntimeOptions()
    else:
        options = DefaultRuntimeOptions()
    return DeploymentRuntimeConfiguration(backend_options=options)


def serialize_deployment_runtime_configuration(
    configuration: DeploymentRuntimeConfiguration,
) -> dict[str, object]:
    """把运行时配置序列化为 JSON 对象。"""

    validate_deployment_runtime_configuration(configuration)
    return asdict(configuration)


def deserialize_deployment_runtime_configuration(
    payload: object,
) -> DeploymentRuntimeConfiguration:
    """从当前版本 JSON 对象恢复运行时配置。

    该函数只接受当前结构，不解释历史字段。
    """

    if not isinstance(payload, dict):
        raise ValueError("runtime_configuration 必须是对象")
    execution_payload = _require_dict(payload, "execution")
    lifecycle_payload = _require_dict(payload, "lifecycle")
    backend_payload = _require_dict(payload, "backend_options")
    execution = DeploymentExecutionPolicy(**execution_payload)
    lifecycle_values = dict(lifecycle_payload)
    image_size = lifecycle_values.get("warmup_dummy_image_size")
    if isinstance(image_size, list):
        lifecycle_values["warmup_dummy_image_size"] = tuple(image_size)
    lifecycle = DeploymentLifecycleOptions(**lifecycle_values)
    kind = backend_payload.get("kind")
    options_type_by_kind: dict[object, type[BackendRuntimeOptions]] = {
        "default": DefaultRuntimeOptions,
        "openvino-cpu": OpenVinoCpuRuntimeOptions,
        "openvino-gpu": OpenVinoGpuRuntimeOptions,
        "openvino-npu": OpenVinoNpuRuntimeOptions,
        "openvino-auto": OpenVinoAutoRuntimeOptions,
        "tensorrt": TensorRtRuntimeOptions,
    }
    options_type = options_type_by_kind.get(kind)
    if options_type is None:
        raise ValueError(f"不支持的 backend_options.kind: {kind}")
    configuration = DeploymentRuntimeConfiguration(
        execution=execution,
        lifecycle=lifecycle,
        backend_options=options_type(**backend_payload),
    )
    validate_deployment_runtime_configuration(configuration)
    return configuration


def validate_deployment_runtime_configuration(
    configuration: DeploymentRuntimeConfiguration,
) -> None:
    """校验完整运行时配置，不依赖 API schema 的隐式转换。"""

    if not isinstance(configuration, DeploymentRuntimeConfiguration):
        raise ValueError("runtime_configuration 类型无效")

    execution = configuration.execution
    _require_integer(
        execution.instance_count,
        field_name="execution.instance_count",
        minimum=1,
        maximum=64,
    )
    _require_choice(
        execution.isolation_level,
        field_name="execution.isolation_level",
        choices={"session"},
    )
    _require_choice(
        execution.overflow_policy,
        field_name="execution.overflow_policy",
        choices={"reject"},
    )
    _require_choice(
        execution.performance_goal,
        field_name="execution.performance_goal",
        choices={"latency", "throughput", "balanced"},
    )

    lifecycle = configuration.lifecycle
    if lifecycle.warmup_dummy_inference_count is not None:
        _require_integer(
            lifecycle.warmup_dummy_inference_count,
            field_name="lifecycle.warmup_dummy_inference_count",
            minimum=0,
        )
    if lifecycle.warmup_dummy_image_size is not None:
        image_size = lifecycle.warmup_dummy_image_size
        if not isinstance(image_size, tuple) or len(image_size) != 2:
            raise ValueError("lifecycle.warmup_dummy_image_size 必须包含宽和高")
        for index, value in enumerate(image_size):
            _require_integer(
                value,
                field_name=f"lifecycle.warmup_dummy_image_size[{index}]",
                minimum=1,
            )
    if lifecycle.keep_warm_enabled is not None and not isinstance(
        lifecycle.keep_warm_enabled, bool
    ):
        raise ValueError("lifecycle.keep_warm_enabled 必须是布尔值")
    if lifecycle.keep_warm_interval_seconds is not None:
        interval = lifecycle.keep_warm_interval_seconds
        if isinstance(interval, bool) or not isinstance(interval, (int, float)):
            raise ValueError("lifecycle.keep_warm_interval_seconds 必须是数字")
        if interval <= 0:
            raise ValueError("lifecycle.keep_warm_interval_seconds 必须大于 0")

    options = configuration.backend_options
    _validate_backend_runtime_options(options)


def _validate_backend_runtime_options(options: BackendRuntimeOptions) -> None:
    """校验 backend 专属参数。"""

    performance_hints = {
        "latency",
        "throughput",
        "cumulative_throughput",
        "none",
    }
    if isinstance(options, DefaultRuntimeOptions):
        _require_choice(
            options.kind, field_name="backend_options.kind", choices={"default"}
        )
        return
    if isinstance(options, OpenVinoCpuRuntimeOptions):
        _require_choice(
            options.kind,
            field_name="backend_options.kind",
            choices={"openvino-cpu"},
        )
        _require_choice(
            options.performance_hint,
            field_name="backend_options.performance_hint",
            choices=performance_hints,
        )
        _require_auto_integer(
            options.inference_num_threads,
            field_name="backend_options.inference_num_threads",
        )
        _require_auto_integer(
            options.num_streams,
            field_name="backend_options.num_streams",
        )
        _require_choice(
            options.scheduling_core_type,
            field_name="backend_options.scheduling_core_type",
            choices={"auto", "any_core", "pcore_only", "ecore_only"},
        )
        _require_auto_boolean(
            options.enable_hyper_threading,
            field_name="backend_options.enable_hyper_threading",
        )
        _require_auto_boolean(
            options.enable_cpu_pinning,
            field_name="backend_options.enable_cpu_pinning",
        )
        return
    if isinstance(options, OpenVinoGpuRuntimeOptions):
        _require_choice(
            options.kind,
            field_name="backend_options.kind",
            choices={"openvino-gpu"},
        )
        _require_choice(
            options.performance_hint,
            field_name="backend_options.performance_hint",
            choices=performance_hints,
        )
        _require_auto_integer(
            options.num_streams,
            field_name="backend_options.num_streams",
        )
        _require_auto_integer(
            options.num_requests,
            field_name="backend_options.num_requests",
        )
        _require_choice(
            options.inference_precision,
            field_name="backend_options.inference_precision",
            choices={"auto", "f32", "f16"},
        )
        for field_name, value in (
            ("queue_priority", options.queue_priority),
            ("queue_throttle", options.queue_throttle),
        ):
            _require_choice(
                value,
                field_name=f"backend_options.{field_name}",
                choices={"auto", "low", "medium", "high"},
            )
        return
    if isinstance(options, OpenVinoNpuRuntimeOptions):
        _require_choice(
            options.kind,
            field_name="backend_options.kind",
            choices={"openvino-npu"},
        )
        _require_choice(
            options.performance_hint,
            field_name="backend_options.performance_hint",
            choices=performance_hints,
        )
        _require_auto_integer(
            options.num_requests,
            field_name="backend_options.num_requests",
        )
        _require_choice(
            options.inference_precision,
            field_name="backend_options.inference_precision",
            choices={"auto", "f16"},
        )
        _require_auto_boolean(options.turbo, field_name="backend_options.turbo")
        _require_auto_integer(options.tiles, field_name="backend_options.tiles")
        if options.compilation_mode_params is not None and not isinstance(
            options.compilation_mode_params, str
        ):
            raise ValueError("backend_options.compilation_mode_params 必须是字符串")
        return
    if isinstance(options, OpenVinoAutoRuntimeOptions):
        _require_choice(
            options.kind,
            field_name="backend_options.kind",
            choices={"openvino-auto"},
        )
        _require_choice(
            options.performance_hint,
            field_name="backend_options.performance_hint",
            choices=performance_hints,
        )
        _require_auto_integer(
            options.num_requests,
            field_name="backend_options.num_requests",
        )
        return
    if isinstance(options, TensorRtRuntimeOptions):
        _require_choice(
            options.kind,
            field_name="backend_options.kind",
            choices={"tensorrt"},
        )
        _require_integer(
            options.optimization_profile_index,
            field_name="backend_options.optimization_profile_index",
            minimum=0,
        )
        if options.pinned_output_buffer_enabled is not None and not isinstance(
            options.pinned_output_buffer_enabled, bool
        ):
            raise ValueError(
                "backend_options.pinned_output_buffer_enabled 必须是布尔值"
            )
        if options.pinned_output_buffer_max_bytes is not None:
            _require_integer(
                options.pinned_output_buffer_max_bytes,
                field_name="backend_options.pinned_output_buffer_max_bytes",
                minimum=0,
            )
        return
    raise ValueError("backend_options 类型无效")


def _require_integer(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int | None = None,
) -> None:
    """校验不接受 bool 的整数范围。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须是整数")
    if value < minimum:
        raise ValueError(f"{field_name} 不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} 不能大于 {maximum}")


def _require_auto_integer(value: object, *, field_name: str) -> None:
    """校验正整数或 auto。"""

    if value == "auto":
        return
    _require_integer(value, field_name=field_name, minimum=1)


def _require_auto_boolean(value: object, *, field_name: str) -> None:
    """校验布尔值或 auto。"""

    if value != "auto" and not isinstance(value, bool):
        raise ValueError(f"{field_name} 必须是布尔值或 auto")


def _require_choice(
    value: object,
    *,
    field_name: str,
    choices: set[str],
) -> None:
    """校验字符串枚举。"""

    if not isinstance(value, str) or value not in choices:
        supported = ", ".join(sorted(choices))
        raise ValueError(f"{field_name} 必须是以下值之一: {supported}")


def _require_dict(payload: dict[object, object], key: str) -> dict[str, object]:
    """读取必填对象字段。"""

    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"runtime_configuration.{key} 必须是对象")
    return {str(item_key): item_value for item_key, item_value in value.items()}
