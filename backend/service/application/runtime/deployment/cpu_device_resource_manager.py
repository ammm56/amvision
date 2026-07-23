"""运行中 OpenVINO CPU deployment 的进程级资源预算管理。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock

from backend.service.application.runtime.deployment.runtime_capabilities import (
    read_cpu_hardware_summary,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    OpenVinoCpuRuntimeOptions,
)


@dataclass(frozen=True)
class CpuDeviceReservation:
    """描述一个运行中 deployment 的 CPU 推理线程预算。"""

    owner_id: str
    deployment_instance_id: str
    runtime_mode: str
    instance_count: int
    threads_per_instance: int
    estimated_thread_demand: int


class CpuDeviceResourceManager:
    """汇总当前进程全部 supervisor 的 OpenVINO CPU 资源预算。"""

    def __init__(self) -> None:
        self._reservations: dict[tuple[str, str], CpuDeviceReservation] = {}
        self._lock = Lock()

    def activate(
        self,
        *,
        owner_id: str,
        deployment_instance_id: str,
        runtime_mode: str,
        runtime_configuration: DeploymentRuntimeConfiguration,
    ) -> None:
        """登记运行中 deployment；非 OpenVINO CPU 配置不会占用 CPU 预算。"""

        key = (owner_id, deployment_instance_id)
        reservation = _build_reservation(
            owner_id=owner_id,
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
            runtime_configuration=runtime_configuration,
        )
        with self._lock:
            if reservation is None:
                self._reservations.pop(key, None)
            else:
                self._reservations[key] = reservation

    def deactivate(self, *, owner_id: str, deployment_instance_id: str) -> None:
        """移除已经停止的 deployment 预算。"""

        with self._lock:
            self._reservations.pop((owner_id, deployment_instance_id), None)

    def deactivate_owner(self, owner_id: str) -> None:
        """移除一个 supervisor 的全部 deployment 预算。"""

        with self._lock:
            keys = tuple(key for key in self._reservations if key[0] == owner_id)
            for key in keys:
                self._reservations.pop(key, None)

    def snapshot(self) -> dict[str, object]:
        """返回当前物理核心预算和全部活动 reservation。"""

        with self._lock:
            reservations = tuple(self._reservations.values())
        hardware = read_cpu_hardware_summary()
        total_demand = sum(item.estimated_thread_demand for item in reservations)
        physical_core_count = int(hardware["cpu_physical_core_count"])
        return {
            "cpu_physical_core_count": physical_core_count,
            "cpu_logical_processor_count": int(
                hardware["cpu_logical_processor_count"]
            ),
            "active_deployment_count": len(reservations),
            "estimated_thread_demand": total_demand,
            "oversubscribed": total_demand > physical_core_count,
            "reservations": [asdict(item) for item in reservations],
        }

    def warnings(self) -> tuple[str, ...]:
        """返回当前全部运行中 deployment 的非阻断预算告警。"""

        snapshot = self.snapshot()
        if snapshot["oversubscribed"] is not True:
            return ()
        return (
            "当前进程运行中的 OpenVINO CPU deployment 线程预算总和 "
            f"{snapshot['estimated_thread_demand']} 超过物理核心数 "
            f"{snapshot['cpu_physical_core_count']}；允许继续运行，但并发节拍可能变慢",
        )


def _build_reservation(
    *,
    owner_id: str,
    deployment_instance_id: str,
    runtime_mode: str,
    runtime_configuration: DeploymentRuntimeConfiguration,
) -> CpuDeviceReservation | None:
    """把 OpenVINO CPU 配置转换为资源 reservation。"""

    options = runtime_configuration.backend_options
    if not isinstance(options, OpenVinoCpuRuntimeOptions):
        return None
    hardware = read_cpu_hardware_summary()
    threads_per_instance = (
        options.inference_num_threads
        if isinstance(options.inference_num_threads, int)
        else int(hardware["cpu_physical_core_count"])
    )
    instance_count = runtime_configuration.instance_count
    return CpuDeviceReservation(
        owner_id=owner_id,
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
        instance_count=instance_count,
        threads_per_instance=threads_per_instance,
        estimated_thread_demand=instance_count * threads_per_instance,
    )


_GLOBAL_CPU_DEVICE_RESOURCE_MANAGER = CpuDeviceResourceManager()


def get_global_cpu_device_resource_manager() -> CpuDeviceResourceManager:
    """返回当前服务进程共享的 CPU device resource manager。"""

    return _GLOBAL_CPU_DEVICE_RESOURCE_MANAGER
