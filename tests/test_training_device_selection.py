from __future__ import annotations

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.device_selection import (
    resolve_single_training_device,
    resolve_single_training_device_name,
    resolve_torch_amp_device_type,
)


class _FakeCuda:
    """模拟 torch.cuda 的最小行为。"""

    def __init__(self, *, available: bool, device_count: int) -> None:
        self._available = available
        self._device_count = device_count

    def is_available(self) -> bool:
        return self._available

    def device_count(self) -> int:
        return self._device_count


class _FakeTorch:
    """模拟训练设备解析需要的 torch 模块。"""

    def __init__(self, *, cuda_available: bool, device_count: int) -> None:
        self.cuda = _FakeCuda(available=cuda_available, device_count=device_count)


def test_default_device_uses_cuda_zero_when_cuda_available() -> None:
    torch_module = _FakeTorch(cuda_available=True, device_count=2)

    selection = resolve_single_training_device(torch_module=torch_module)

    assert selection.device_name == "cuda:0"
    assert selection.device_index == 0
    assert selection.device_ids == (0,)
    assert selection.gpu_count == 1


def test_explicit_cuda_index_selects_single_gpu() -> None:
    torch_module = _FakeTorch(cuda_available=True, device_count=3)

    selection = resolve_single_training_device(
        torch_module=torch_module,
        extra_options={"device": "cuda:1"},
    )

    assert selection.device_name == "cuda:1"
    assert selection.device_index == 1
    assert selection.lightning_accelerator == "gpu"
    assert selection.lightning_devices == [1]


def test_auto_falls_back_to_cpu_without_cuda() -> None:
    torch_module = _FakeTorch(cuda_available=False, device_count=0)

    assert resolve_single_training_device_name(torch_module=torch_module) == "cpu"


def test_explicit_cuda_without_cuda_is_rejected() -> None:
    torch_module = _FakeTorch(cuda_available=False, device_count=0)

    with pytest.raises(InvalidRequestError):
        resolve_single_training_device(
            torch_module=torch_module,
            extra_options={"device": "cuda"},
        )


def test_out_of_range_cuda_index_is_rejected() -> None:
    torch_module = _FakeTorch(cuda_available=True, device_count=1)

    with pytest.raises(InvalidRequestError):
        resolve_single_training_device(
            torch_module=torch_module,
            extra_options={"device": "cuda:1"},
        )


def test_amp_device_type_uses_cuda_for_indexed_cuda_name() -> None:
    assert resolve_torch_amp_device_type("cuda:1") == "cuda"
    assert resolve_torch_amp_device_type("cpu") == "cpu"
