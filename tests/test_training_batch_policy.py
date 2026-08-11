"""训练 Batch 执行策略测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.batch_policy import (
    resolve_training_batch_size,
    select_largest_safe_batch_size,
)


def test_selector_uses_growth_and_binary_search() -> None:
    probes: list[int] = []

    selected = select_largest_safe_batch_size(
        minimum_size=1,
        maximum_size=32,
        target_peak_bytes=100,
        probe=lambda batch: probes.append(batch) or batch * 9,
    )

    assert selected == 11
    assert probes[:5] == [1, 2, 4, 8, 16]
    assert len(probes) < 12


def test_selector_handles_oom_as_unsafe() -> None:
    assert select_largest_safe_batch_size(
        minimum_size=2,
        maximum_size=16,
        target_peak_bytes=100,
        probe=lambda batch: None if batch >= 8 else batch * 10,
    ) == 7


def test_auto_batch_uses_cpu_fallback_without_cuda_probe() -> None:
    resolution = resolve_training_batch_size(
        torch_module=SimpleNamespace(),
        model=SimpleNamespace(),
        device_name="cpu",
        input_size=(640, 640),
        dataset_size=3,
        requested_batch_size=None,
        default_batch_size=16,
        runtime_precision="fp32",
        extra_options={"batch_mode": "auto"},
    )
    assert resolution.batch_size == 3
    assert resolution.mode == "auto-cpu-fallback"


def test_fixed_batch_requires_requested_value() -> None:
    with pytest.raises(InvalidRequestError, match="缺少 batch_size"):
        resolve_training_batch_size(
            torch_module=SimpleNamespace(),
            model=SimpleNamespace(),
            device_name="cpu",
            input_size=(640, 640),
            dataset_size=10,
            requested_batch_size=None,
            default_batch_size=1,
            runtime_precision="fp32",
            extra_options={"batch_mode": "fixed"},
        )


def test_resume_reuses_checkpoint_batch() -> None:
    resolution = resolve_training_batch_size(
        torch_module=SimpleNamespace(),
        model=SimpleNamespace(),
        device_name="cuda:0",
        input_size=(640, 640),
        dataset_size=100,
        requested_batch_size=None,
        default_batch_size=1,
        runtime_precision="fp16",
        extra_options={"batch_mode": "auto"},
        resume_batch_size=24,
    )
    assert resolution.batch_size == 24
    assert resolution.mode == "resume"
