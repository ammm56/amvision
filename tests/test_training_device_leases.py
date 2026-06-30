from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.tasks.task_records import TaskRecord
from backend.workers.training.device_assignment import read_requested_training_device
from backend.workers.training.device_leases import TrainingDeviceLeaseManager


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
    """模拟设备租约读取 CUDA inventory 的 torch 模块。"""

    def __init__(self, *, cuda_available: bool, device_count: int) -> None:
        self.cuda = _FakeCuda(available=cuda_available, device_count=device_count)


def test_auto_training_device_lease_uses_next_free_cuda() -> None:
    manager = TrainingDeviceLeaseManager()
    torch_module = _FakeTorch(cuda_available=True, device_count=2)

    with manager.acquire("auto", torch_module=torch_module) as first:
        with manager.acquire("auto", torch_module=torch_module) as second:
            assert first.resolved_device == "cuda:0"
            assert second.resolved_device == "cuda:1"


def test_auto_training_device_lease_reuses_cuda_after_release() -> None:
    manager = TrainingDeviceLeaseManager()
    torch_module = _FakeTorch(cuda_available=True, device_count=1)

    with manager.acquire("auto", torch_module=torch_module) as first:
        assert first.resolved_device == "cuda:0"

    with manager.acquire("auto", torch_module=torch_module) as second:
        assert second.resolved_device == "cuda:0"


def test_auto_training_device_lease_falls_back_to_cpu_without_cuda() -> None:
    manager = TrainingDeviceLeaseManager()
    torch_module = _FakeTorch(cuda_available=False, device_count=0)

    with manager.acquire("auto", torch_module=torch_module) as lease:
        assert lease.resolved_device == "cpu"


def test_explicit_cuda_training_device_lease_rejects_invalid_index() -> None:
    manager = TrainingDeviceLeaseManager()
    torch_module = _FakeTorch(cuda_available=True, device_count=1)

    try:
        manager.acquire("cuda:2", torch_module=torch_module)
    except InvalidRequestError as error:
        assert error.details["cuda_count"] == 1
    else:
        raise AssertionError("invalid CUDA device should be rejected")


def test_training_device_assignment_prefers_original_requested_device() -> None:
    task_record = TaskRecord(
        task_id="task-1",
        task_kind="yolo11-training",
        project_id="project-1",
        task_spec={
            "extra_options": {
                "requested_device": "auto",
                "device": "cuda:1",
            }
        },
    )

    assert read_requested_training_device(task_record) == "auto"
