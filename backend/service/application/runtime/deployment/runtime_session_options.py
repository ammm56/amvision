"""deployment 配置到具体 runtime session 参数的转换。"""

from __future__ import annotations

from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    TensorRtRuntimeOptions,
    build_default_runtime_configuration,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)


def resolve_runtime_session_configuration(
    *,
    runtime_target: RuntimeTargetSnapshot,
    configuration: DeploymentRuntimeConfiguration | None,
) -> DeploymentRuntimeConfiguration:
    """为 deployment 外的直接 session 调用补充 backend/device 默认配置。"""

    return configuration or build_default_runtime_configuration(
        runtime_backend=runtime_target.runtime_backend,
        device_name=runtime_target.device_name,
    )


def build_tensorrt_session_load_options(
    configuration: DeploymentRuntimeConfiguration,
) -> dict[str, object]:
    """构建 TensorRT session 加载参数。"""

    options = require_tensorrt_runtime_options(configuration)
    return {
        "pinned_output_buffer_enabled": options.pinned_output_buffer_enabled,
        "pinned_output_buffer_max_bytes": options.pinned_output_buffer_max_bytes,
        "optimization_profile_index": options.optimization_profile_index,
    }


def require_tensorrt_runtime_options(
    configuration: DeploymentRuntimeConfiguration,
) -> TensorRtRuntimeOptions:
    """读取并校验 TensorRT backend_options。"""

    options = configuration.backend_options
    if not isinstance(options, TensorRtRuntimeOptions):
        raise ValueError("TensorRT deployment 缺少 tensorrt backend_options")
    return options
