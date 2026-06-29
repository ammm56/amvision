"""普通 YOLO detection 多 GPU 资源解析测试。"""

from __future__ import annotations

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.training import (
    resolve_yolo_training_runtime_resources,
)


class _FakeCuda:
    """模拟 torch.cuda 的最小接口。"""

    def __init__(self, *, available: bool, device_count: int) -> None:
        """保存 CUDA 可用状态和设备数量。"""

        self._available = available
        self._device_count = device_count

    def is_available(self) -> bool:
        """返回模拟 CUDA 可用状态。"""

        return self._available

    def device_count(self) -> int:
        """返回模拟 GPU 数量。"""

        return self._device_count


class _FakeTorch:
    """模拟 torch 模块中资源解析需要的部分。"""

    def __init__(self, *, cuda_available: bool, device_count: int) -> None:
        """创建带有 CUDA 子模块的 fake torch。"""

        self.cuda = _FakeCuda(
            available=cuda_available,
            device_count=device_count,
        )


def test_yolo_detection_runtime_uses_requested_gpu_count() -> None:
    """gpu_count 大于 1 时应解析成单进程 DataParallel 资源。"""

    runtime = resolve_yolo_training_runtime_resources(
        torch_module=_FakeTorch(cuda_available=True, device_count=4),
        requested_gpu_count=2,
        requested_precision="fp16",
    )

    assert runtime.device == "cuda:0"
    assert runtime.gpu_count == 2
    assert runtime.device_ids == (0, 1)
    assert runtime.distributed_mode == "data-parallel"
    assert runtime.precision == "fp16"


def test_yolo_detection_runtime_respects_cuda_device_offset() -> None:
    """device=cuda:<index> 时应从指定 GPU 开始分配连续设备。"""

    runtime = resolve_yolo_training_runtime_resources(
        torch_module=_FakeTorch(cuda_available=True, device_count=4),
        requested_gpu_count=2,
        requested_precision="fp32",
        extra_options={"device": "cuda:1"},
    )

    assert runtime.device == "cuda:1"
    assert runtime.device_ids == (1, 2)
    assert runtime.distributed_mode == "data-parallel"


def test_yolo_detection_runtime_rejects_gpu_count_without_cuda() -> None:
    """没有 CUDA 时显式指定 gpu_count 应直接报错，避免静默回退。"""

    with pytest.raises(InvalidRequestError):
        resolve_yolo_training_runtime_resources(
            torch_module=_FakeTorch(cuda_available=False, device_count=0),
            requested_gpu_count=2,
            requested_precision="fp32",
        )


def test_yolo_detection_runtime_rejects_cpu_with_gpu_count() -> None:
    """device=cpu 与 gpu_count 不能同时出现。"""

    with pytest.raises(InvalidRequestError):
        resolve_yolo_training_runtime_resources(
            torch_module=_FakeTorch(cuda_available=True, device_count=2),
            requested_gpu_count=1,
            requested_precision="fp32",
            extra_options={"device": "cpu"},
        )
