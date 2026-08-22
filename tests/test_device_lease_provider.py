"""跨进程 DeviceLeaseProvider 合约测试。"""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from backend.service.application.runtime.device_leases import (
    CudaDeviceResolver,
    CudaDeviceResource,
    DeviceLeaseMode,
    DeviceLeaseProvider,
    DeviceLeaseUnavailableError,
)
import backend.service.application.runtime.device_leases as device_leases_module


_TEST_RESOURCE = CudaDeviceResource(
    cuda_index=0,
    device_name="cuda:0",
    resource_key="GPU-11111111-2222-3333-4444-555555555555",
)


class _CudaWithoutUuid:
    """模拟只暴露 CUDA index、不暴露 UUID 的 torch.cuda。"""

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def device_count() -> int:
        return 1

    @staticmethod
    def get_device_properties(_cuda_index: int) -> object:
        return SimpleNamespace()


def _hold_device_lease(
    root_dir: str,
    ready_path: str,
    mode_value: str = DeviceLeaseMode.EXCLUSIVE.value,
) -> None:
    """子进程持续持有指定模式的 lease。"""

    provider = DeviceLeaseProvider(root_dir=root_dir, poll_interval_seconds=0.01)
    with provider.acquire_resource(
        _TEST_RESOURCE,
        requested_device="cuda:0",
        mode=DeviceLeaseMode(mode_value),
        purpose="crash-test",
        owner_id="child",
        timeout_seconds=0.0,
    ):
        Path(ready_path).write_text("ready", encoding="utf-8")
        while True:
            sleep(1.0)


def test_shared_deployment_reservations_can_coexist(tmp_path: Path) -> None:
    """多个 deployment shared reservation 可以长期并存。"""

    first_provider = DeviceLeaseProvider(root_dir=tmp_path)
    second_provider = DeviceLeaseProvider(root_dir=tmp_path)
    with first_provider.acquire_resource(
        _TEST_RESOURCE,
        requested_device="cuda:0",
        mode=DeviceLeaseMode.SHARED,
        purpose="deployment",
        owner_id="deployment-1",
        timeout_seconds=0.0,
    ) as first:
        with second_provider.acquire_resource(
            _TEST_RESOURCE,
            requested_device="cuda:0",
            mode=DeviceLeaseMode.SHARED,
            purpose="deployment",
            owner_id="deployment-2",
            timeout_seconds=0.0,
        ) as second:
            assert first.info.resource_key == _TEST_RESOURCE.resource_key
            assert second.info.mode == "shared"


def test_exclusive_and_shared_reservations_reject_each_other(tmp_path: Path) -> None:
    """training/conversion 独占 lease 与常驻 deployment shared reservation 双向冲突。"""

    provider = DeviceLeaseProvider(root_dir=tmp_path, poll_interval_seconds=0.01)
    other = DeviceLeaseProvider(root_dir=tmp_path, poll_interval_seconds=0.01)
    with provider.acquire_resource(
        _TEST_RESOURCE,
        requested_device="cuda:0",
        mode=DeviceLeaseMode.SHARED,
        purpose="deployment",
        owner_id="deployment",
        timeout_seconds=0.0,
    ):
        with pytest.raises(DeviceLeaseUnavailableError) as captured:
            other.acquire_resource(
                _TEST_RESOURCE,
                requested_device="cuda:0",
                mode=DeviceLeaseMode.EXCLUSIVE,
                purpose="training",
                owner_id="training",
                timeout_seconds=0.0,
            )
        assert captured.value.code == "device_lease_unavailable"

    with provider.acquire_resource(
        _TEST_RESOURCE,
        requested_device="cuda:0",
        mode=DeviceLeaseMode.EXCLUSIVE,
        purpose="conversion",
        owner_id="conversion",
        timeout_seconds=0.0,
    ):
        with pytest.raises(DeviceLeaseUnavailableError):
            other.acquire_resource(
                _TEST_RESOURCE,
                requested_device="cuda:0",
                mode=DeviceLeaseMode.SHARED,
                purpose="deployment",
                owner_id="deployment",
                timeout_seconds=0.0,
            )


def test_device_lease_timeout_is_bounded(tmp_path: Path) -> None:
    """busy 策略使用单一有界 timeout，不会无限排队。"""

    provider = DeviceLeaseProvider(root_dir=tmp_path, poll_interval_seconds=0.01)
    other = DeviceLeaseProvider(root_dir=tmp_path, poll_interval_seconds=0.01)
    with provider.acquire_resource(
        _TEST_RESOURCE,
        requested_device="cuda:0",
        mode=DeviceLeaseMode.EXCLUSIVE,
        purpose="training",
        owner_id="first",
        timeout_seconds=0.0,
    ):
        started_at = monotonic()
        with pytest.raises(DeviceLeaseUnavailableError):
            other.acquire_resource(
                _TEST_RESOURCE,
                requested_device="cuda:0",
                mode=DeviceLeaseMode.EXCLUSIVE,
                purpose="training",
                owner_id="second",
                timeout_seconds=0.08,
            )
        elapsed = monotonic() - started_at
    assert elapsed >= 0.07
    assert elapsed < 0.5


def test_cpu_lease_does_not_create_or_hold_os_lock(tmp_path: Path) -> None:
    """CPU 路径不参与 GPU 协调。"""

    provider = DeviceLeaseProvider(root_dir=tmp_path)
    with provider.cpu_lease(
        requested_device="cpu",
        purpose="training",
        owner_id="cpu-task",
    ) as lease:
        assert lease.info.resource_key is None
        assert lease.info.mode == "none"
        assert tuple(tmp_path.iterdir()) == ()


def test_numeric_cuda_visibility_maps_to_physical_gpu_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CUDA_VISIBLE_DEVICES 重排后仍使用对应物理 GPU UUID 作为资源键。"""

    expected_uuid = "GPU-22222222-3333-4444-5555-666666666666"
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2")
    monkeypatch.setattr(
        device_leases_module,
        "_read_nvidia_smi_gpu_uuids",
        lambda: {2: expected_uuid},
    )
    resources = CudaDeviceResolver().list_visible_devices(
        torch_module=SimpleNamespace(cuda=_CudaWithoutUuid())
    )

    assert resources[0].device_name == "cuda:0"
    assert resources[0].resource_key == expected_uuid


def test_process_crash_releases_device_lease_automatically(tmp_path: Path) -> None:
    """持锁进程被强制终止后，OS 自动释放 GPU lease。"""

    context = multiprocessing.get_context("spawn")
    ready_path = tmp_path / "child-ready"
    process = context.Process(
        target=_hold_device_lease,
        args=(str(tmp_path), str(ready_path)),
    )
    process.start()
    try:
        deadline = monotonic() + 10.0
        while not ready_path.is_file() and monotonic() < deadline:
            sleep(0.02)
        assert ready_path.is_file()
        provider = DeviceLeaseProvider(root_dir=tmp_path)
        with pytest.raises(DeviceLeaseUnavailableError):
            provider.acquire_resource(
                _TEST_RESOURCE,
                requested_device="cuda:0",
                mode=DeviceLeaseMode.EXCLUSIVE,
                purpose="training",
                owner_id="parent-before-crash",
                timeout_seconds=0.0,
            )

        process.terminate()
        process.join(timeout=10.0)
        assert not process.is_alive()
        with provider.acquire_resource(
            _TEST_RESOURCE,
            requested_device="cuda:0",
            mode=DeviceLeaseMode.EXCLUSIVE,
            purpose="training",
            owner_id="parent-after-crash",
            timeout_seconds=1.0,
        ) as lease:
            assert lease.info.owner_id == "parent-after-crash"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=10.0)


def test_shared_reservations_coexist_across_processes(tmp_path: Path) -> None:
    """跨进程 shared deployment reservation 可并存且会阻止 exclusive。"""

    context = multiprocessing.get_context("spawn")
    ready_path = tmp_path / "shared-child-ready"
    process = context.Process(
        target=_hold_device_lease,
        args=(
            str(tmp_path),
            str(ready_path),
            DeviceLeaseMode.SHARED.value,
        ),
    )
    process.start()
    try:
        deadline = monotonic() + 10.0
        while not ready_path.is_file() and monotonic() < deadline:
            sleep(0.02)
        assert ready_path.is_file()
        provider = DeviceLeaseProvider(root_dir=tmp_path)
        with provider.acquire_resource(
            _TEST_RESOURCE,
            requested_device="cuda:0",
            mode=DeviceLeaseMode.SHARED,
            purpose="deployment",
            owner_id="parent-deployment",
            timeout_seconds=0.0,
        ):
            with pytest.raises(DeviceLeaseUnavailableError):
                provider.acquire_resource(
                    _TEST_RESOURCE,
                    requested_device="cuda:0",
                    mode=DeviceLeaseMode.EXCLUSIVE,
                    purpose="conversion",
                    owner_id="parent-conversion",
                    timeout_seconds=0.0,
                )
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=10.0)
