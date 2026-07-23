"""TensorRT execution context 的统一运行时控制。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError


def activate_tensorrt_optimization_profile(
    *,
    engine: object,
    context: object,
    stream: object,
    profile_index: int,
) -> None:
    """在复用 stream 上激活明确的 optimization profile。"""

    profile_count = int(getattr(engine, "num_optimization_profiles", 1))
    if profile_index < 0 or profile_index >= profile_count:
        raise ServiceConfigurationError(
            "TensorRT optimization profile 超出 engine 范围",
            details={
                "optimization_profile_index": profile_index,
                "optimization_profile_count": profile_count,
            },
        )
    if profile_index == 0:
        return
    activate = getattr(context, "set_optimization_profile_async", None)
    if not callable(activate):
        raise ServiceConfigurationError(
            "当前 TensorRT runtime 不支持切换 optimization profile",
            details={"optimization_profile_index": profile_index},
        )
    activated = activate(profile_index, stream)
    if activated is False:
        raise ServiceConfigurationError(
            "TensorRT optimization profile 激活失败",
            details={"optimization_profile_index": profile_index},
        )
