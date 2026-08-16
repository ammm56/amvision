"""运行中 OpenVINO CPU deployment 的共享线程配置管理。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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
    """描述一个运行中 deployment 的 CPU 推理线程有效配置。"""

    owner_id: str
    deployment_instance_id: str
    runtime_mode: str
    instance_count: int
    physical_core_count: int
    requested_threads_per_instance: int | str
    requested_thread_demand: int
    allocated_threads_per_instance: int
    allocated_thread_count: int
    constrained: bool
    overcommitted: bool


class CpuDeviceResourceManager:
    """按单个 OpenVINO CPU deployment 生成共享 CPU 的有效线程配置。"""

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
        """登记 deployment 并返回传给 OpenVINO 的有效配置。

        每个 deployment 只按自身 ``instance_count`` 划分主机物理核心。其他已启动但空闲的
        deployment 不会扣减可用线程，也不会阻止当前 deployment 启动。多个 deployment
        真正同时执行时由 OpenVINO 和操作系统共享调度 CPU。
        """

        key = (owner_id, deployment_instance_id)
        options = runtime_configuration.backend_options
        with self._lock:
            if not isinstance(options, OpenVinoCpuRuntimeOptions):
                self._reservations.pop(key, None)
                return runtime_configuration
            hardware = read_cpu_hardware_summary()
            physical_core_count = max(1, int(hardware["cpu_physical_core_count"]))
            reservation = _build_reservation(
                owner_id=owner_id,
                deployment_instance_id=deployment_instance_id,
                runtime_mode=runtime_mode,
                runtime_configuration=runtime_configuration,
                physical_core_count=physical_core_count,
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
        """删除已经停止的 deployment 线程配置记录。"""

        with self._lock:
            self._reservations.pop((owner_id, deployment_instance_id), None)

    def release_owner(self, owner_id: str) -> None:
        """删除一个 supervisor 的全部 deployment 线程配置记录。"""

        with self._lock:
            keys = tuple(key for key in self._reservations if key[0] == owner_id)
            for key in keys:
                self._reservations.pop(key, None)

    def snapshot(self) -> dict[str, object]:
        """返回共享调度策略和全部活动 deployment 的线程配置。"""

        with self._lock:
            reservations = tuple(self._reservations.values())
        hardware = read_cpu_hardware_summary()
        requested_thread_capacity = sum(
            item.requested_thread_demand for item in reservations
        )
        configured_thread_capacity = sum(
            item.allocated_thread_count for item in reservations
        )
        physical_core_count = max(1, int(hardware["cpu_physical_core_count"]))
        return {
            "scheduling_policy": "per_deployment_shared",
            "cpu_physical_core_count": physical_core_count,
            "cpu_logical_processor_count": int(
                hardware["cpu_logical_processor_count"]
            ),
            "active_deployment_count": len(reservations),
            "requested_thread_capacity": requested_thread_capacity,
            "configured_thread_capacity": configured_thread_capacity,
            "shared_thread_capacity": physical_core_count,
            "constrained_deployment_count": sum(
                1 for item in reservations if item.constrained
            ),
            "overcommitted_deployment_count": sum(
                1 for item in reservations if item.overcommitted
            ),
            # 兼容已发布 health 消费方。这里表达配置容量，不代表长期独占或实时占用。
            "requested_thread_demand": requested_thread_capacity,
            "allocated_thread_count": configured_thread_capacity,
            "available_thread_count": physical_core_count,
            "oversubscribed": False,
            "reservations": [asdict(item) for item in reservations],
        }

    def warnings(
        self,
        *,
        owner_id: str | None = None,
        deployment_instance_id: str | None = None,
    ) -> tuple[str, ...]:
        """返回匹配 deployment 的线程裁剪和并发超配告警。"""

        snapshot = self.snapshot()
        warnings: list[str] = []
        for item in snapshot["reservations"]:
            if not isinstance(item, dict):
                continue
            if owner_id is not None and item.get("owner_id") != owner_id:
                continue
            if (
                deployment_instance_id is not None
                and item.get("deployment_instance_id") != deployment_instance_id
            ):
                continue
            if item.get("constrained") is True:
                warnings.append(
                    "OpenVINO CPU deployment "
                    f"{item['deployment_instance_id']} 请求每实例线程数 "
                    f"{item['requested_threads_per_instance']}，按当前主机物理核心数和本 deployment "
                    f"实例数裁剪为 {item['allocated_threads_per_instance']}"
                )
            if item.get("overcommitted") is True:
                warnings.append(
                    "OpenVINO CPU deployment "
                    f"{item['deployment_instance_id']} 的实例并发线程容量 "
                    f"{item['allocated_thread_count']} 超过物理核心数 "
                    f"{item['physical_core_count']}；满载时由操作系统共享调度，延迟可能上升"
                )
        return tuple(warnings)


def _build_reservation(
    *,
    owner_id: str,
    deployment_instance_id: str,
    runtime_mode: str,
    runtime_configuration: DeploymentRuntimeConfiguration,
    physical_core_count: int,
) -> CpuDeviceReservation:
    """按单个 deployment 的实例数生成 OpenVINO CPU 有效线程配置。"""

    options = runtime_configuration.backend_options
    if not isinstance(options, OpenVinoCpuRuntimeOptions):  # pragma: no cover
        raise TypeError("CPU reservation 只接受 OpenVINO CPU 配置")
    instance_count = runtime_configuration.instance_count
    requested_value = options.inference_num_threads
    requested_threads_per_instance = (
        requested_value if isinstance(requested_value, int) else physical_core_count
    )
    allocated_threads_per_instance = min(
        requested_threads_per_instance,
        max(1, physical_core_count // instance_count),
    )
    requested_thread_demand = instance_count * requested_threads_per_instance
    allocated_thread_count = instance_count * allocated_threads_per_instance
    return CpuDeviceReservation(
        owner_id=owner_id,
        deployment_instance_id=deployment_instance_id,
        runtime_mode=runtime_mode,
        instance_count=instance_count,
        physical_core_count=physical_core_count,
        requested_threads_per_instance=requested_value,
        requested_thread_demand=requested_thread_demand,
        allocated_threads_per_instance=allocated_threads_per_instance,
        allocated_thread_count=allocated_thread_count,
        constrained=allocated_thread_count < requested_thread_demand,
        overcommitted=allocated_thread_count > physical_core_count,
    )


_GLOBAL_CPU_DEVICE_RESOURCE_MANAGER = CpuDeviceResourceManager()


def get_global_cpu_device_resource_manager() -> CpuDeviceResourceManager:
    """返回当前服务进程共享的 CPU device resource manager。"""

    return _GLOBAL_CPU_DEVICE_RESOURCE_MANAGER
