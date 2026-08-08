"""运行中 OpenVINO CPU deployment 的进程级资源预算管理。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from threading import Lock

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.deployment.runtime_capabilities import (
    read_cpu_hardware_summary,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    OpenVinoCpuRuntimeOptions,
)


@dataclass(frozen=True)
class CpuDeviceReservation:
    """描述一个运行中 deployment 的 CPU 推理线程预留。"""

    owner_id: str
    deployment_instance_id: str
    runtime_mode: str
    instance_count: int
    requested_threads_per_instance: int | str
    requested_thread_demand: int
    allocated_threads_per_instance: int
    allocated_thread_count: int
    constrained: bool


class CpuDeviceResourceManager:
    """为当前进程全部 OpenVINO CPU deployment 分配物理核心预算。"""

    def __init__(self) -> None:
        self._reservations: dict[tuple[str, str], CpuDeviceReservation] = {}
        self._lock = Lock()

    def reserve(
        self,
        *,
        owner_id: str,
        deployment_instance_id: str,
        runtime_mode: str,
        runtime_configuration: DeploymentRuntimeConfiguration,
    ) -> DeploymentRuntimeConfiguration:
        """原子预留 CPU 线程，并返回传给 OpenVINO 的有效配置。

        每个实例至少需要一个推理线程。请求值超过剩余物理核心时会被统一裁剪；连最小实例预算
        都无法满足时拒绝启动，避免创建必然超额订阅且节拍不可预测的常驻进程。
        """

        key = (owner_id, deployment_instance_id)
        options = runtime_configuration.backend_options
        with self._lock:
            if not isinstance(options, OpenVinoCpuRuntimeOptions):
                self._reservations.pop(key, None)
                return runtime_configuration
            hardware = read_cpu_hardware_summary()
            physical_core_count = max(1, int(hardware["cpu_physical_core_count"]))
            other_allocated_thread_count = sum(
                item.allocated_thread_count
                for reservation_key, item in self._reservations.items()
                if reservation_key != key
            )
            available_thread_count = max(
                0,
                physical_core_count - other_allocated_thread_count,
            )
            reservation = _build_reservation(
                owner_id=owner_id,
                deployment_instance_id=deployment_instance_id,
                runtime_mode=runtime_mode,
                runtime_configuration=runtime_configuration,
                physical_core_count=physical_core_count,
                available_thread_count=available_thread_count,
            )
            self._reservations[key] = reservation
        return replace(
            runtime_configuration,
            backend_options=replace(
                options,
                inference_num_threads=reservation.allocated_threads_per_instance,
            ),
        )

    def release(self, *, owner_id: str, deployment_instance_id: str) -> None:
        """释放已经停止的 deployment 线程预留。"""

        with self._lock:
            self._reservations.pop((owner_id, deployment_instance_id), None)

    def release_owner(self, owner_id: str) -> None:
        """释放一个 supervisor 的全部 deployment 线程预留。"""

        with self._lock:
            keys = tuple(key for key in self._reservations if key[0] == owner_id)
            for key in keys:
                self._reservations.pop(key, None)

    def snapshot(self) -> dict[str, object]:
        """返回当前物理核心预算和全部活动 reservation。"""

        with self._lock:
            reservations = tuple(self._reservations.values())
        hardware = read_cpu_hardware_summary()
        requested_thread_demand = sum(
            item.requested_thread_demand for item in reservations
        )
        allocated_thread_count = sum(
            item.allocated_thread_count for item in reservations
        )
        physical_core_count = int(hardware["cpu_physical_core_count"])
        return {
            "cpu_physical_core_count": physical_core_count,
            "cpu_logical_processor_count": int(
                hardware["cpu_logical_processor_count"]
            ),
            "active_deployment_count": len(reservations),
            "requested_thread_demand": requested_thread_demand,
            "allocated_thread_count": allocated_thread_count,
            "available_thread_count": max(
                0, physical_core_count - allocated_thread_count
            ),
            "constrained_deployment_count": sum(
                1 for item in reservations if item.constrained
            ),
            "oversubscribed": allocated_thread_count > physical_core_count,
            "reservations": [asdict(item) for item in reservations],
        }

    def warnings(
        self,
        *,
        owner_id: str | None = None,
        deployment_instance_id: str | None = None,
    ) -> tuple[str, ...]:
        """返回匹配 deployment 的线程裁剪告警以及全局异常告警。"""

        snapshot = self.snapshot()
        warnings = [
            "OpenVINO CPU 资源调度异常：已分配线程总数 "
            f"{snapshot['allocated_thread_count']} 超过物理核心数 "
            f"{snapshot['cpu_physical_core_count']}"
        ] if snapshot["oversubscribed"] is True else []
        for item in snapshot["reservations"]:
            if not isinstance(item, dict) or item.get("constrained") is not True:
                continue
            if owner_id is not None and item.get("owner_id") != owner_id:
                continue
            if (
                deployment_instance_id is not None
                and item.get("deployment_instance_id") != deployment_instance_id
            ):
                continue
            warnings.append(
                "OpenVINO CPU deployment "
                f"{item['deployment_instance_id']} 请求线程总数 "
                f"{item['requested_thread_demand']}，资源调度器实际分配 "
                f"{item['allocated_thread_count']}"
            )
        return tuple(warnings)


def _build_reservation(
    *,
    owner_id: str,
    deployment_instance_id: str,
    runtime_mode: str,
    runtime_configuration: DeploymentRuntimeConfiguration,
    physical_core_count: int,
    available_thread_count: int,
) -> CpuDeviceReservation:
    """把 OpenVINO CPU 请求转换为严格受物理核心预算约束的预留。"""

    options = runtime_configuration.backend_options
    if not isinstance(options, OpenVinoCpuRuntimeOptions):  # pragma: no cover
        raise TypeError("CPU reservation 只接受 OpenVINO CPU 配置")
    instance_count = runtime_configuration.instance_count
    requested_value = options.inference_num_threads
    requested_threads_per_instance = (
        requested_value if isinstance(requested_value, int) else physical_core_count
    )
    minimum_thread_count = instance_count
    if available_thread_count < minimum_thread_count:
        raise InvalidRequestError(
            "OpenVINO CPU 可用线程不足，无法为每个推理实例分配至少一个线程",
            details={
                "deployment_instance_id": deployment_instance_id,
                "runtime_mode": runtime_mode,
                "instance_count": instance_count,
                "cpu_physical_core_count": physical_core_count,
                "available_thread_count": available_thread_count,
                "minimum_thread_count": minimum_thread_count,
            },
        )
    allocated_threads_per_instance = min(
        requested_threads_per_instance,
        max(1, available_thread_count // instance_count),
    )
    requested_thread_demand = instance_count * requested_threads_per_instance
    allocated_thread_count = instance_count * allocated_threads_per_instance
    return CpuDeviceReservation(
        owner_id=owner_id,
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
        instance_count=instance_count,
        requested_threads_per_instance=requested_value,
        requested_thread_demand=requested_thread_demand,
        allocated_threads_per_instance=allocated_threads_per_instance,
        allocated_thread_count=allocated_thread_count,
        constrained=allocated_thread_count < requested_thread_demand,
    )


_GLOBAL_CPU_DEVICE_RESOURCE_MANAGER = CpuDeviceResourceManager()


def get_global_cpu_device_resource_manager() -> CpuDeviceResourceManager:
    """返回当前服务进程共享的 CPU device resource manager。"""

    return _GLOBAL_CPU_DEVICE_RESOURCE_MANAGER
