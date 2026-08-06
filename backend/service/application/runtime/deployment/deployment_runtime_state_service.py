"""Deployment runtime state 持久化应用服务。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
)
from backend.service.domain.deployments.deployment_runtime_state import (
    DEPLOYMENT_RUNTIME_MODES,
    DeploymentRuntimeDesiredState,
    DeploymentRuntimeMode,
    DeploymentRuntimeObservedState,
    DeploymentRuntimeState,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class DeploymentRuntimeStateService:
    """管理 deployment runtime 的期望状态、观测状态和 controller lease。"""

    def __init__(self, *, session_factory: SessionFactory) -> None:
        """绑定数据库会话工厂。"""

        self.session_factory = session_factory

    def ensure_runtime_states(
        self,
        deployment_instance_id: str,
    ) -> tuple[DeploymentRuntimeState, ...]:
        """为旧 DeploymentInstance 补齐 sync/async 默认 stopped 状态。"""

        normalized_id = deployment_instance_id.strip()
        if not normalized_id:
            raise InvalidRequestError("deployment_instance_id 不能为空")
        now = _now_isoformat()
        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            states: list[DeploymentRuntimeState] = []
            changed = False
            for runtime_mode in DEPLOYMENT_RUNTIME_MODES:
                state = unit_of_work.deployment_runtime_states.get_deployment_runtime_state(
                    normalized_id,
                    runtime_mode,
                )
                if state is None:
                    state = DeploymentRuntimeState(
                        deployment_instance_id=normalized_id,
                        runtime_mode=runtime_mode,
                        created_at=now,
                        updated_at=now,
                    )
                    unit_of_work.deployment_runtime_states.save_deployment_runtime_state(
                        state
                    )
                    changed = True
                states.append(state)
            if changed:
                try:
                    unit_of_work.commit()
                except PersistenceOperationError:
                    # 旧数据库首次补齐时，两个 service/daemon 可能同时插入。
                    # 唯一键冲突后回滚并确认另一事务已完整补齐；其他故障照常抛出。
                    unit_of_work.rollback()
                    concurrent_states = tuple(
                        unit_of_work.deployment_runtime_states.get_deployment_runtime_state(
                            normalized_id,
                            runtime_mode,
                        )
                        for runtime_mode in DEPLOYMENT_RUNTIME_MODES
                    )
                    if all(state is not None for state in concurrent_states):
                        return tuple(
                            state for state in concurrent_states if state is not None
                        )
                    raise
            return tuple(states)
        finally:
            unit_of_work.close()

    def get_runtime_state(
        self,
        *,
        deployment_instance_id: str,
        runtime_mode: DeploymentRuntimeMode,
    ) -> DeploymentRuntimeState:
        """读取状态，不存在时按升级兼容规则创建默认状态。"""

        self.ensure_runtime_states(deployment_instance_id)
        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            state = unit_of_work.deployment_runtime_states.get_deployment_runtime_state(
                deployment_instance_id,
                runtime_mode,
            )
            assert state is not None
            return state
        finally:
            unit_of_work.close()

    def set_desired_state(
        self,
        *,
        deployment_instance_id: str,
        runtime_mode: DeploymentRuntimeMode,
        desired_state: DeploymentRuntimeDesiredState,
    ) -> DeploymentRuntimeState:
        """更新期望状态并递增 generation，使旧 controller 回写失效。"""

        for _attempt in range(8):
            current = self.get_runtime_state(
                deployment_instance_id=deployment_instance_id,
                runtime_mode=runtime_mode,
            )
            now = _now_isoformat()
            updated = replace(
                current,
                desired_state=desired_state,
                generation=current.generation + 1,
                controller_owner_id=None,
                controller_lease_expires_at=None,
                next_restart_at=None,
                last_error_code=(
                    None if desired_state == "running" else current.last_error_code
                ),
                last_error_message=(
                    None if desired_state == "running" else current.last_error_message
                ),
                updated_at=now,
            )
            if self._try_save(updated, expected_generation=current.generation):
                return updated
        raise PersistenceOperationError(
            "更新 Deployment runtime 期望状态发生并发冲突",
            details={
                "deployment_instance_id": deployment_instance_id,
                "runtime_mode": runtime_mode,
            },
        )

    def record_observed_state(
        self,
        *,
        deployment_instance_id: str,
        runtime_mode: DeploymentRuntimeMode,
        generation: int,
        observed_state: DeploymentRuntimeObservedState,
        process_id: int | None,
        restart_count: int,
        last_error_message: str | None = None,
        last_error_code: str | None = None,
        next_restart_at: str | None = None,
        consecutive_failure_count: int | None = None,
    ) -> DeploymentRuntimeState:
        """仅在 generation 仍匹配时写入 controller 观测状态。"""

        current = self.get_runtime_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
        )
        if current.generation != generation:
            return current
        now = _now_isoformat()
        successful = observed_state == "running"
        stopped = observed_state == "stopped"
        updated = replace(
            current,
            observed_state=observed_state,
            process_id=process_id,
            heartbeat_at=now if process_id is not None else current.heartbeat_at,
            # supervisor 在 daemon 重启后会从 0 重新计数；持久层必须保持
            # 单调不减，避免运维界面把历史重启次数错误地重置为 0。
            restart_count=max(current.restart_count, max(0, int(restart_count))),
            consecutive_failure_count=(
                0
                if successful
                else (
                    current.consecutive_failure_count
                    if consecutive_failure_count is None
                    else max(0, consecutive_failure_count)
                )
            ),
            next_restart_at=next_restart_at,
            last_started_at=now if successful else current.last_started_at,
            last_stopped_at=now if stopped else current.last_stopped_at,
            last_error_code=last_error_code,
            last_error_message=last_error_message,
            updated_at=now,
        )
        if self._try_save(updated, expected_generation=generation):
            return updated
        return self.get_runtime_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
        )

    def list_desired_running_states(self) -> tuple[DeploymentRuntimeState, ...]:
        """列出需要由 controller 恢复的全部 runtime state。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            return unit_of_work.deployment_runtime_states.list_deployment_runtime_states(
                desired_state="running"
            )
        finally:
            unit_of_work.close()

    def record_process_status(
        self,
        *,
        deployment_instance_id: str,
        runtime_mode: DeploymentRuntimeMode,
        generation: int,
        process_status: object,
        failure: bool = False,
    ) -> DeploymentRuntimeState:
        """把 DeploymentProcessStatus 兼容对象写入持久化状态。"""

        process_state = str(getattr(process_status, "process_state", "stopped"))
        observed_state: DeploymentRuntimeObservedState
        if failure or process_state == "crashed":
            observed_state = "failed"
        elif process_state == "running":
            observed_state = "running"
        else:
            observed_state = "stopped"
        current = self.get_runtime_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
        )
        consecutive_failures = (
            current.consecutive_failure_count + 1
            if observed_state == "failed"
            else current.consecutive_failure_count
        )
        return self.record_observed_state(
            deployment_instance_id=deployment_instance_id,
            runtime_mode=runtime_mode,
            generation=generation,
            observed_state=observed_state,
            process_id=getattr(process_status, "process_id", None),
            restart_count=int(getattr(process_status, "restart_count", 0)),
            last_error_message=getattr(process_status, "last_error", None),
            last_error_code=("deployment_process_failed" if observed_state == "failed" else None),
            consecutive_failure_count=consecutive_failures,
        )

    def try_claim(
        self,
        *,
        state: DeploymentRuntimeState,
        owner_id: str,
        lease_seconds: float,
    ) -> bool:
        """尝试领取或续租指定 runtime state。"""

        now = datetime.now(timezone.utc)
        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            claimed = unit_of_work.deployment_runtime_states.try_claim_deployment_runtime_state(
                deployment_instance_id=state.deployment_instance_id,
                runtime_mode=state.runtime_mode,
                expected_generation=state.generation,
                owner_id=owner_id,
                now=now.isoformat(),
                lease_expires_at=(now + timedelta(seconds=max(1.0, lease_seconds))).isoformat(),
            )
            unit_of_work.commit()
            return claimed
        finally:
            unit_of_work.close()

    def _save(self, state: DeploymentRuntimeState) -> None:
        """在独立短事务中保存状态。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            unit_of_work.deployment_runtime_states.save_deployment_runtime_state(state)
            unit_of_work.commit()
        finally:
            unit_of_work.close()

    def _try_save(
        self,
        state: DeploymentRuntimeState,
        *,
        expected_generation: int,
    ) -> bool:
        """在独立短事务中按 generation 原子保存状态。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            saved = unit_of_work.deployment_runtime_states.try_save_deployment_runtime_state(
                state,
                expected_generation=expected_generation,
            )
            unit_of_work.commit()
            return saved
        finally:
            unit_of_work.close()


def _now_isoformat() -> str:
    """返回 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat()
