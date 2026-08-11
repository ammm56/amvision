"""训练 Automatic Mixed Precision 运行时策略。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class TrainingAmpRuntime:
    """描述一次训练实际采用的 AMP 模式。"""

    enabled: bool
    precision: str
    dtype: Any | None
    scaler_enabled: bool


def resolve_training_amp_runtime(
    *,
    torch_module: Any,
    device_name: str,
    requested_precision: str | None,
    extra_options: dict[str, object] | None,
) -> TrainingAmpRuntime:
    """把公开 AMP 策略解析为设备上真实可执行的 precision。

    AMP 始终保留 FP32 模型主权重。``precision`` 只描述 autocast dtype，
    不能据此对训练模型调用 ``half()`` 或 ``bfloat16()``。
    """

    def resolved(runtime: TrainingAmpRuntime) -> TrainingAmpRuntime:
        """登记 TrainingEngine 实际 AMP 配置后返回。"""

        from backend.service.application.models.training.training_engine import (
            record_active_training_amp_resolution,
        )

        record_active_training_amp_resolution(
            enabled=runtime.enabled,
            precision=runtime.precision,
            device_name=device_name,
            scaler_enabled=runtime.scaler_enabled,
        )
        return runtime

    options = dict(extra_options or {})
    mode = str(options.get("amp_mode", "auto")).strip().lower()
    dtype = str(options.get("amp_dtype", "auto")).strip().lower()

    # 兼容内部旧 DTO，但公开 API 已统一写入 amp_mode/amp_dtype。
    if requested_precision == "fp32" and "amp_mode" not in options:
        mode = "disabled"
    elif requested_precision in {"fp16", "bf16"} and "amp_mode" not in options:
        mode = "enabled"
        dtype = str(requested_precision)

    if mode not in {"auto", "enabled", "disabled"}:
        raise InvalidRequestError(
            "amp_mode 必须是 auto、enabled 或 disabled",
            details={"amp_mode": mode},
        )
    if dtype not in {"auto", "fp16", "bf16"}:
        raise InvalidRequestError(
            "amp_dtype 必须是 auto、fp16 或 bf16",
            details={"amp_dtype": dtype},
        )
    if mode == "disabled":
        if dtype != "auto":
            raise InvalidRequestError("AMP 关闭时 amp_dtype 必须是 auto")
        return resolved(TrainingAmpRuntime(False, "fp32", None, False))

    is_cuda = str(device_name).startswith("cuda")
    if not is_cuda:
        if mode == "enabled":
            raise InvalidRequestError(
                "当前训练 AMP 仅支持 CUDA 设备",
                details={"device": device_name, "amp_dtype": dtype},
            )
        return resolved(TrainingAmpRuntime(False, "fp32", None, False))

    resolved_dtype = "fp16" if dtype == "auto" else dtype
    if resolved_dtype == "bf16" and not _cuda_bf16_is_supported(torch_module):
        if mode == "enabled":
            raise InvalidRequestError(
                "当前 CUDA 设备不支持 BF16 AMP",
                details={"device": device_name},
            )
        resolved_dtype = "fp16"

    torch_dtype_name = "float16" if resolved_dtype == "fp16" else "bfloat16"
    torch_dtype = getattr(torch_module, torch_dtype_name, None)
    if torch_dtype is None:
        raise InvalidRequestError(
            "当前 PyTorch 运行时缺少请求的 AMP dtype",
            details={"amp_dtype": resolved_dtype},
        )
    return resolved(
        TrainingAmpRuntime(
            enabled=True,
            precision=resolved_dtype,
            dtype=torch_dtype,
            scaler_enabled=resolved_dtype == "fp16",
        )
    )


def build_training_autocast_context(
    *,
    torch_module: Any,
    device_name: str,
    runtime: TrainingAmpRuntime,
) -> Any:
    """构建统一的 autocast context factory。"""

    if not runtime.enabled:
        return nullcontext
    amp_module = getattr(torch_module, "amp", None)
    autocast = getattr(amp_module, "autocast", None) if amp_module is not None else None
    if callable(autocast):
        return lambda: autocast(
            "cuda",
            dtype=runtime.dtype,
            enabled=True,
        )
    if runtime.precision != "fp16":
        raise InvalidRequestError("当前 PyTorch 版本不支持 BF16 autocast")
    return lambda: torch_module.cuda.amp.autocast(enabled=True)


def _cuda_bf16_is_supported(torch_module: Any) -> bool:
    """兼容不同 PyTorch 版本判断 CUDA BF16 能力。"""

    cuda = getattr(torch_module, "cuda", None)
    checker = getattr(cuda, "is_bf16_supported", None) if cuda is not None else None
    return bool(callable(checker) and checker())


__all__ = [
    "TrainingAmpRuntime",
    "build_training_autocast_context",
    "resolve_training_amp_runtime",
]
