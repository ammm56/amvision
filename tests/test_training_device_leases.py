from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.tasks.task_records import TaskRecord
from backend.workers.training.device_assignment import (
    activate_training_cuda_device,
    read_requested_training_device,
)
from backend.workers.training.device_leases import (
    TrainingDeviceLeaseInfo,
    TrainingDeviceLeaseManager,
    TrainingDeviceLease,
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
    """模拟设备租约读取 CUDA inventory 的 torch 模块。"""

    def __init__(self, *, cuda_available: bool, device_count: int) -> None:
        self.cuda = _FakeCuda(available=cuda_available, device_count=device_count)


class _FakeCurrentCuda(_FakeCuda):
    """模拟 torch.cuda current device 切换。"""

    def __init__(self) -> None:
        super().__init__(available=True, device_count=2)
        self.current_index = 0
        self.set_history: list[int] = []

    def current_device(self) -> int:
        return self.current_index

    def set_device(self, cuda_index: int) -> None:
        self.current_index = cuda_index
        self.set_history.append(cuda_index)


class _FakeCurrentTorch:
    """模拟带 current device 的 torch 模块。"""

    def __init__(self) -> None:
        self.cuda = _FakeCurrentCuda()


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


def test_training_device_assignment_activates_cuda_current_device() -> None:
    manager = TrainingDeviceLeaseManager()
    lease = TrainingDeviceLease(
        manager=manager,
        info=TrainingDeviceLeaseInfo(
            requested_device="auto",
            resolved_device="cuda:1",
            cuda_index=1,
            waited_seconds=0.0,
        ),
    )
    torch_module = _FakeCurrentTorch()

    with activate_training_cuda_device(lease, torch_module=torch_module):
        assert torch_module.cuda.current_index == 1

    assert torch_module.cuda.current_index == 0
    assert torch_module.cuda.set_history == [1, 0]
