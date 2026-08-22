from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.device_leases import (
    CudaDeviceResolver,
    CudaDeviceResource,
    DeviceLeaseMode,
    DeviceLeaseProvider,
    DeviceLeaseProviderConfig,
    DeviceLeaseUnavailableError,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.workers.training.device_assignment import (
    activate_training_cuda_device,
    assigned_training_device,
    read_requested_training_device,
)
import backend.workers.training.device_assignment as device_assignment_module


class _FakeCuda:
    """模拟 torch.cuda 的最小行为。"""

    def __init__(self, *, available: bool, device_count: int) -> None:
        self._available = available
        self._device_count = device_count

    def is_available(self) -> bool:
        return self._available

    def device_count(self) -> int:
        return self._device_count

    def get_device_properties(self, cuda_index: int) -> object:
        return SimpleNamespace(
            uuid=f"GPU-00000000-0000-0000-0000-{cuda_index:012d}"
        )


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


class _StaticCudaResolver:
    """为训练边界集成测试提供固定 GPU UUID。"""

    resource = CudaDeviceResource(
        cuda_index=0,
        device_name="cuda:0",
        resource_key="GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    def list_visible_devices(self, *, torch_module: object | None = None):
        return (self.resource,)

    def resolve(self, device_name: str, *, torch_module: object | None = None):
        assert device_name == "cuda:0"
        return self.resource


def test_auto_training_device_lease_uses_next_free_cuda(tmp_path: Path) -> None:
    first_provider = DeviceLeaseProvider(root_dir=tmp_path)
    second_provider = DeviceLeaseProvider(root_dir=tmp_path)
    torch_module = _FakeTorch(cuda_available=True, device_count=2)

    with first_provider.acquire_cuda(
        "auto",
        mode=DeviceLeaseMode.EXCLUSIVE,
        purpose="training",
        owner_id="task-1",
        timeout_seconds=0.0,
        torch_module=torch_module,
    ) as first:
        with second_provider.acquire_cuda(
            "auto",
            mode=DeviceLeaseMode.EXCLUSIVE,
            purpose="training",
            owner_id="task-2",
            timeout_seconds=0.0,
            torch_module=torch_module,
        ) as second:
            assert first.resolved_device == "cuda:0"
            assert second.resolved_device == "cuda:1"


def test_auto_training_device_lease_reuses_cuda_after_release(tmp_path: Path) -> None:
    provider = DeviceLeaseProvider(root_dir=tmp_path)
    torch_module = _FakeTorch(cuda_available=True, device_count=1)

    with provider.acquire_cuda(
        "auto",
        mode=DeviceLeaseMode.EXCLUSIVE,
        purpose="training",
        owner_id="task-1",
        timeout_seconds=0.0,
        torch_module=torch_module,
    ) as first:
        assert first.resolved_device == "cuda:0"

    with provider.acquire_cuda(
        "auto",
        mode=DeviceLeaseMode.EXCLUSIVE,
        purpose="training",
        owner_id="task-2",
        timeout_seconds=0.0,
        torch_module=torch_module,
    ) as second:
        assert second.resolved_device == "cuda:0"


def test_auto_training_device_lease_falls_back_to_cpu_without_cuda(
    tmp_path: Path,
) -> None:
    provider = DeviceLeaseProvider(root_dir=tmp_path)
    torch_module = _FakeTorch(cuda_available=False, device_count=0)

    with provider.acquire_cuda(
        "auto",
        mode=DeviceLeaseMode.EXCLUSIVE,
        purpose="training",
        owner_id="task-1",
        timeout_seconds=0.0,
        torch_module=torch_module,
    ) as lease:
        assert lease.resolved_device == "cpu"


def test_explicit_cuda_training_device_lease_rejects_invalid_index(
    tmp_path: Path,
) -> None:
    provider = DeviceLeaseProvider(root_dir=tmp_path)
    torch_module = _FakeTorch(cuda_available=True, device_count=1)

    try:
        provider.acquire_cuda(
            "cuda:2",
            mode=DeviceLeaseMode.EXCLUSIVE,
            purpose="training",
            owner_id="task-1",
            timeout_seconds=0.0,
            torch_module=torch_module,
        )
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


def test_training_device_assignment_activates_cuda_current_device(
    tmp_path: Path,
) -> None:
    provider = DeviceLeaseProvider(
        root_dir=tmp_path,
        resolver=CudaDeviceResolver(
            uuid_overrides={
                "cuda:0": "GPU-00000000-0000-0000-0000-000000000000",
                "cuda:1": "GPU-00000000-0000-0000-0000-000000000001",
            }
        ),
    )
    torch_module = _FakeCurrentTorch()

    with provider.acquire_cuda(
        "cuda:1",
        mode=DeviceLeaseMode.EXCLUSIVE,
        purpose="training",
        owner_id="task-1",
        timeout_seconds=0.0,
        torch_module=torch_module,
    ) as lease:
        with activate_training_cuda_device(lease, torch_module=torch_module):
            assert torch_module.cuda.current_index == 1

    assert torch_module.cuda.current_index == 0
    assert torch_module.cuda.set_history == [1, 0]


def test_training_boundary_acquires_exclusive_gpu_and_records_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """训练 worker 入口在写任务状态前获取 exclusive lease，并完整回写诊断。"""

    resolver = _StaticCudaResolver()
    provider = DeviceLeaseProvider(root_dir=tmp_path, resolver=resolver)
    competing_provider = DeviceLeaseProvider(root_dir=tmp_path, resolver=resolver)
    task_record = TaskRecord(
        task_id="training-task-1",
        task_kind="yolo11-training",
        project_id="project-1",
        task_spec={"extra_options": {"device": "cuda:0"}},
    )
    updates: list[dict[str, object]] = []
    events: list[object] = []

    class _FakeTaskService:
        def get_task(self, task_id: str):
            assert task_id == task_record.task_id
            return SimpleNamespace(task=task_record)

        def update_task_spec_and_metadata(self, task_id: str, **kwargs: object):
            assert task_id == task_record.task_id
            updates.append(dict(kwargs))

        def append_task_event(self, request: object):
            events.append(request)

    @contextmanager
    def _no_op_cuda_activation(_lease):
        yield

    monkeypatch.setattr(
        device_assignment_module,
        "SqlAlchemyTaskService",
        lambda *, session_factory: _FakeTaskService(),
    )
    monkeypatch.setattr(
        device_assignment_module,
        "activate_training_cuda_device",
        _no_op_cuda_activation,
    )
    config = DeviceLeaseProviderConfig(
        root_dir=str(tmp_path),
        exclusive_acquire_timeout_seconds=0.0,
    )

    with competing_provider.acquire_resource(
        resolver.resource,
        requested_device="cuda:0",
        mode=DeviceLeaseMode.SHARED,
        purpose="deployment",
        owner_id="deployment-1",
        timeout_seconds=0.0,
    ):
        with pytest.raises(DeviceLeaseUnavailableError):
            with assigned_training_device(
                session_factory=object(),
                task_id=task_record.task_id,
                device_lease_provider=provider,
                device_lease_config=config,
            ):
                raise AssertionError("冲突时不应进入训练正文")
    assert updates == []
    assert events == []

    with assigned_training_device(
        session_factory=object(),
        task_id=task_record.task_id,
        device_lease_provider=provider,
        device_lease_config=config,
    ) as lease:
        assert lease.info.mode == "exclusive"
        assert lease.info.resource_key == resolver.resource.resource_key

    assignment = updates[0]["metadata"]["training_device_assignment"]
    assert assignment["resource_key"] == resolver.resource.resource_key
    assert assignment["owner_id"] == task_record.task_id
    assert len(events) == 1
