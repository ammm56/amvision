"""训练 AMP 运行时策略测试。"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.amp_policy import (
    build_training_autocast_context,
    build_training_autocast_context_for_precision,
    resolve_training_amp_runtime,
)


class _FakeAutocast:
    """记录 autocast 调用参数。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> nullcontext:
        self.calls.append((args, kwargs))
        return nullcontext()


def _torch(*, bf16_supported: bool = True) -> SimpleNamespace:
    autocast = _FakeAutocast()
    return SimpleNamespace(
        float16="torch.float16",
        bfloat16="torch.bfloat16",
        amp=SimpleNamespace(autocast=autocast),
        cuda=SimpleNamespace(is_bf16_supported=lambda: bf16_supported),
    )


def test_auto_amp_uses_fp16_on_cuda() -> None:
    torch_module = _torch()
    runtime = resolve_training_amp_runtime(
        torch_module=torch_module,
        device_name="cuda:0",
        requested_precision=None,
        extra_options={"amp_mode": "auto", "amp_dtype": "auto"},
    )

    assert runtime.enabled is True
    assert runtime.precision == "fp16"
    assert runtime.scaler_enabled is True
    with build_training_autocast_context(
        torch_module=torch_module,
        device_name="cuda:0",
        runtime=runtime,
    )():
        pass
    assert torch_module.amp.autocast.calls == [
        (("cuda",), {"dtype": "torch.float16", "enabled": True})
    ]


def test_auto_amp_falls_back_to_fp32_on_cpu() -> None:
    runtime = resolve_training_amp_runtime(
        torch_module=_torch(),
        device_name="cpu",
        requested_precision=None,
        extra_options={"amp_mode": "auto", "amp_dtype": "auto"},
    )
    assert runtime.enabled is False
    assert runtime.precision == "fp32"


def test_explicit_bf16_requires_device_support() -> None:
    with pytest.raises(InvalidRequestError, match="不支持 BF16"):
        resolve_training_amp_runtime(
            torch_module=_torch(bf16_supported=False),
            device_name="cuda:0",
            requested_precision=None,
            extra_options={"amp_mode": "enabled", "amp_dtype": "bf16"},
        )


def test_legacy_fp16_request_remains_supported() -> None:
    runtime = resolve_training_amp_runtime(
        torch_module=_torch(),
        device_name="cuda:0",
        requested_precision="fp16",
        extra_options={},
    )
    assert runtime.precision == "fp16"


def test_resolved_fp16_evaluation_uses_cuda_autocast() -> None:
    """验证训练期评估按已解析 FP16 precision 进入 CUDA autocast。"""

    torch_module = _torch()
    with build_training_autocast_context_for_precision(
        torch_module=torch_module,
        device_name="cuda:0",
        precision="fp16",
    )():
        pass

    assert torch_module.amp.autocast.calls == [
        (("cuda",), {"dtype": "torch.float16", "enabled": True})
    ]
