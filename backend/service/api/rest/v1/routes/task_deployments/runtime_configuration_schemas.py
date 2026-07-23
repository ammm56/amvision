"""模型部署运行时配置 API schema。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.service.domain.deployments.deployment_runtime_configuration import (
    DefaultRuntimeOptions,
    DeploymentExecutionPolicy,
    DeploymentLifecycleOptions,
    DeploymentRuntimeConfiguration,
    OpenVinoAutoRuntimeOptions,
    OpenVinoCpuRuntimeOptions,
    OpenVinoGpuRuntimeOptions,
    OpenVinoNpuRuntimeOptions,
    TensorRtRuntimeOptions,
)

PositiveInteger = Annotated[int, Field(ge=1)]


class _StrictModel(BaseModel):
    """拒绝未定义字段，避免运行时配置静默失效。"""

    model_config = ConfigDict(extra="forbid")


class DeploymentExecutionPolicyBody(_StrictModel):
    """平台执行策略。"""

    instance_count: int = Field(
        default=1, ge=1, le=64, description="独立 runtime session 数量"
    )
    isolation_level: Literal["session"] = Field(
        default="session", description="实例隔离级别"
    )
    overflow_policy: Literal["reject"] = Field(
        default="reject", description="实例满载时立即拒绝"
    )
    performance_goal: Literal["latency", "throughput", "balanced"] = Field(
        default="latency",
        description="平台级性能目标",
    )


class DeploymentLifecycleOptionsBody(_StrictModel):
    """deployment 预热和 keep-warm 配置。"""

    warmup_dummy_inference_count: int | None = Field(default=None, ge=0)
    warmup_dummy_image_size: tuple[int, int] | None = None
    keep_warm_enabled: bool | None = None
    keep_warm_interval_seconds: float | None = Field(default=None, gt=0)


class DefaultRuntimeOptionsBody(_StrictModel):
    """无专属配置的 runtime backend。"""

    kind: Literal["default"] = "default"


class OpenVinoCpuRuntimeOptionsBody(_StrictModel):
    """OpenVINO CPU plugin 配置。"""

    kind: Literal["openvino-cpu"] = "openvino-cpu"
    performance_hint: Literal[
        "latency", "throughput", "cumulative_throughput", "none"
    ] = "latency"
    inference_num_threads: PositiveInteger | Literal["auto"] = "auto"
    num_streams: PositiveInteger | Literal["auto"] = 1
    scheduling_core_type: Literal["auto", "any_core", "pcore_only", "ecore_only"] = (
        "auto"
    )
    enable_hyper_threading: bool | Literal["auto"] = "auto"
    enable_cpu_pinning: bool | Literal["auto"] = "auto"


class OpenVinoGpuRuntimeOptionsBody(_StrictModel):
    """OpenVINO GPU plugin 配置。"""

    kind: Literal["openvino-gpu"] = "openvino-gpu"
    performance_hint: Literal[
        "latency", "throughput", "cumulative_throughput", "none"
    ] = "latency"
    num_streams: PositiveInteger | Literal["auto"] = 1
    num_requests: PositiveInteger | Literal["auto"] = "auto"
    inference_precision: Literal["auto", "f32", "f16"] = "auto"
    queue_priority: Literal["auto", "low", "medium", "high"] = "auto"
    queue_throttle: Literal["auto", "low", "medium", "high"] = "auto"


class OpenVinoNpuRuntimeOptionsBody(_StrictModel):
    """OpenVINO NPU plugin 配置。"""

    kind: Literal["openvino-npu"] = "openvino-npu"
    performance_hint: Literal[
        "latency", "throughput", "cumulative_throughput", "none"
    ] = "latency"
    num_requests: PositiveInteger | Literal["auto"] = "auto"
    inference_precision: Literal["auto", "f16"] = "auto"
    turbo: bool | Literal["auto"] = "auto"
    tiles: PositiveInteger | Literal["auto"] = "auto"
    compilation_mode_params: str | None = None


class OpenVinoAutoRuntimeOptionsBody(_StrictModel):
    """OpenVINO AUTO/MULTI 配置。"""

    kind: Literal["openvino-auto"] = "openvino-auto"
    performance_hint: Literal[
        "latency", "throughput", "cumulative_throughput", "none"
    ] = "latency"
    num_requests: PositiveInteger | Literal["auto"] = "auto"


class TensorRtRuntimeOptionsBody(_StrictModel):
    """TensorRT engine runtime 配置。"""

    kind: Literal["tensorrt"] = "tensorrt"
    optimization_profile_index: int = Field(default=0, ge=0)
    pinned_output_buffer_enabled: bool | None = None
    pinned_output_buffer_max_bytes: int | None = Field(default=None, ge=0)


BackendRuntimeOptionsBody = Annotated[
    DefaultRuntimeOptionsBody
    | OpenVinoCpuRuntimeOptionsBody
    | OpenVinoGpuRuntimeOptionsBody
    | OpenVinoNpuRuntimeOptionsBody
    | OpenVinoAutoRuntimeOptionsBody
    | TensorRtRuntimeOptionsBody,
    Field(discriminator="kind"),
]


class DeploymentRuntimeConfigurationBody(_StrictModel):
    """DeploymentInstance 完整运行时配置。"""

    execution: DeploymentExecutionPolicyBody = Field(
        default_factory=DeploymentExecutionPolicyBody
    )
    lifecycle: DeploymentLifecycleOptionsBody = Field(
        default_factory=DeploymentLifecycleOptionsBody
    )
    backend_options: BackendRuntimeOptionsBody

    def to_domain(self) -> DeploymentRuntimeConfiguration:
        """转换为领域对象。"""

        options_type_by_kind = {
            "default": DefaultRuntimeOptions,
            "openvino-cpu": OpenVinoCpuRuntimeOptions,
            "openvino-gpu": OpenVinoGpuRuntimeOptions,
            "openvino-npu": OpenVinoNpuRuntimeOptions,
            "openvino-auto": OpenVinoAutoRuntimeOptions,
            "tensorrt": TensorRtRuntimeOptions,
        }
        options_payload = self.backend_options.model_dump()
        options_type = options_type_by_kind[options_payload["kind"]]
        return DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(**self.execution.model_dump()),
            lifecycle=DeploymentLifecycleOptions(**self.lifecycle.model_dump()),
            backend_options=options_type(**options_payload),
        )

    @classmethod
    def from_domain(
        cls,
        configuration: DeploymentRuntimeConfiguration,
    ) -> "DeploymentRuntimeConfigurationBody":
        """从领域对象构建 API 响应。"""

        return cls.model_validate(asdict(configuration))
