"""Deployment runtime 持久化期望状态协调器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Event, Lock, Thread
from typing import Protocol
from uuid import uuid4
import logging

from backend.service.application.deployments.deployment_instance_service import (
    SqlAlchemyDeploymentInstanceService,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.application.runtime.deployment.deployment_runtime_state_service import (
    DeploymentRuntimeStateService,
)
from backend.service.domain.deployments.deployment_runtime_state import (
    DeploymentRuntimeMode,
    DeploymentRuntimeState,
)
from backend.service.settings import BackendServiceDeploymentRuntimeReconcilerConfig


LOGGER = logging.getLogger(__name__)


class AsyncInferenceGatewayRegistry(Protocol):
    """描述协调器需要的 async gateway registry 最小接口。"""

    def ensure_dispatcher_for_deployment(self, deployment_instance_id: str) -> object:
        """确保 deployment 的 dispatcher 已启动。"""

        ...

    def stop_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        """停止 deployment 的 dispatcher。"""

        ...


@dataclass(frozen=True)
class DeploymentRuntimeBinding:
    """描述一个 task type 与 sync/async 运行组件的绑定。"""

    deployment_service: SqlAlchemyDeploymentInstanceService
    sync_supervisor: DeploymentProcessSupervisor
    async_supervisor: DeploymentProcessSupervisor
    async_gateway_registry: AsyncInferenceGatewayRegistry

    def get_supervisor(
        self, runtime_mode: DeploymentRuntimeMode
    ) -> DeploymentProcessSupervisor:
        """按 runtime mode 返回 supervisor。"""

        return self.sync_supervisor if runtime_mode == "sync" else self.async_supervisor


class DeploymentRuntimeReconciler:
    """把数据库 desired state 持续收敛为实际 deployment 子进程状态。"""

    def __init__(
        self,
        *,
        state_service: DeploymentRuntimeStateService,
        lookup_service: SqlAlchemyDeploymentInstanceService,
        bindings_by_task_type: dict[str, DeploymentRuntimeBinding],
        settings: BackendServiceDeploymentRuntimeReconcilerConfig,
        controller_id: str | None = None,
    ) -> None:
        """绑定状态服务、deployment 服务、运行组件和协调参数。"""

        self.state_service = state_service
        self.lookup_service = lookup_service
        self.bindings_by_task_type = dict(bindings_by_task_type)
        self.settings = settings
        self.controller_id = controller_id or f"deployment-controller-{uuid4().hex}"
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lifecycle_lock = Lock()

    @property
    def is_running(self) -> bool:
        """返回协调线程是否存活。"""

        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """启动协调线程；线程启动后立即执行第一轮恢复。"""

        if not self.settings.enabled:
            return
        with self._lifecycle_lock:
            if self.is_running:
                return
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run_loop,
                name="deployment-runtime-reconciler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """停止协调线程，不改变持久化 desired state。"""

        with self._lifecycle_lock:
            self._stop_event.set()
            thread = self._thread
        if thread is not None:
            thread.join(
                timeout=max(1.0, self.settings.reconcile_interval_seconds * 2)
            )
        with self._lifecycle_lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def reconcile_once(self) -> None:
        """执行一轮协调；单条 deployment 失败不会阻断其余恢复。"""

        for state in self.state_service.list_desired_running_states():
            try:
                self._reconcile_running_state(state)
            except Exception as error:  # noqa: BLE001 - 协调循环必须隔离单项失败
                self._record_reconcile_failure(state, error)

    def _run_loop(self) -> None:
        """持续执行协调并隔离数据库临时故障。"""

        while not self._stop_event.is_set():
            try:
                self.reconcile_once()
            except Exception:  # noqa: BLE001 - 后续轮次应继续尝试恢复
                LOGGER.exception("deployment runtime 协调循环发生异常，将继续重试")
            self._stop_event.wait(self.settings.reconcile_interval_seconds)

    def _reconcile_running_state(self, state: DeploymentRuntimeState) -> None:
        """恢复或续租一条 desired=running 状态。"""

        if _is_future_timestamp(state.next_restart_at):
            return
        if not self.state_service.try_claim(
            state=state,
            owner_id=self.controller_id,
            lease_seconds=self.settings.controller_lease_seconds,
        ):
            return

        current = self.state_service.get_runtime_state(
            deployment_instance_id=state.deployment_instance_id,
            runtime_mode=state.runtime_mode,
        )
        if current.generation != state.generation or current.desired_state != "running":
            return

        view = self.lookup_service.get_deployment_instance(state.deployment_instance_id)
        binding = self.bindings_by_task_type.get(view.task_type)
        if binding is None:
            raise RuntimeError(f"未注册 deployment task type: {view.task_type}")
        process_config = binding.deployment_service.resolve_process_config(
            state.deployment_instance_id
        )
        supervisor = binding.get_supervisor(state.runtime_mode)
        status = supervisor.get_status(process_config)
        if status.process_state != "running":
            # 每次由持久化协调器重建缺失进程都属于一次恢复重启。
            # supervisor 的进程内计数在 daemon 重启后会归零，因此先在
            # 持久层累加，再由状态服务的单调合并保留历史值。
            recovery_restart_count = current.restart_count + 1
            self.state_service.record_observed_state(
                deployment_instance_id=state.deployment_instance_id,
                runtime_mode=state.runtime_mode,
                generation=state.generation,
                observed_state="starting",
                process_id=None,
                restart_count=recovery_restart_count,
            )
            status = supervisor.start_deployment(process_config)

        latest = self.state_service.get_runtime_state(
            deployment_instance_id=state.deployment_instance_id,
            runtime_mode=state.runtime_mode,
        )
        if latest.generation != state.generation or latest.desired_state != "running":
            supervisor.stop_deployment(process_config)
            if state.runtime_mode == "async":
                binding.async_gateway_registry.stop_dispatcher_for_deployment(
                    state.deployment_instance_id
                )
            return
        if state.runtime_mode == "async":
            binding.async_gateway_registry.ensure_dispatcher_for_deployment(
                state.deployment_instance_id
            )
        self.state_service.record_process_status(
            deployment_instance_id=state.deployment_instance_id,
            runtime_mode=state.runtime_mode,
            generation=state.generation,
            process_status=status,
        )

    def _record_reconcile_failure(
        self,
        state: DeploymentRuntimeState,
        error: Exception,
    ) -> None:
        """记录启动失败和指数退避时间。"""

        current = self.state_service.get_runtime_state(
            deployment_instance_id=state.deployment_instance_id,
            runtime_mode=state.runtime_mode,
        )
        if current.generation != state.generation or current.desired_state != "running":
            return
        failure_count = current.consecutive_failure_count + 1
        delay = self._build_restart_delay(state, failure_count)
        self.state_service.record_observed_state(
            deployment_instance_id=state.deployment_instance_id,
            runtime_mode=state.runtime_mode,
            generation=state.generation,
            observed_state="failed",
            process_id=None,
            restart_count=current.restart_count,
            last_error_code="deployment_reconcile_failed",
            last_error_message=str(error),
            next_restart_at=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(),
            consecutive_failure_count=failure_count,
        )

    def _build_restart_delay(
        self,
        state: DeploymentRuntimeState,
        failure_count: int,
    ) -> float:
        """构建有上限且带稳定抖动的指数退避秒数。"""

        maximum = self.settings.restart_backoff_max_seconds
        base = min(maximum, self.settings.restart_backoff_initial_seconds)
        remaining_doublings = max(0, failure_count - 1)
        # 达到上限后立即停止倍增，运行次数只与配置的退避范围相关，不与可能很大的失败计数相关。
        while remaining_doublings > 0 and base < maximum:
            base = min(maximum, base * 2.0)
            remaining_doublings -= 1
        digest = sha256(
            f"{state.deployment_instance_id}:{state.runtime_mode}".encode("utf-8")
        ).digest()
        unit = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        jitter = (unit * 2.0 - 1.0) * self.settings.restart_backoff_jitter_ratio
        minimum = min(0.1, maximum)
        return min(maximum, max(minimum, base * (1.0 + jitter)))


def _is_future_timestamp(value: str | None) -> bool:
    """判断 ISO 8601 时间是否仍在未来。"""

    if value is None:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed > datetime.now(timezone.utc)
