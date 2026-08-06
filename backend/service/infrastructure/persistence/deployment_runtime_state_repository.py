"""Deployment runtime state 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.deployments.deployment_runtime_state import (
    DeploymentRuntimeMode,
    DeploymentRuntimeState,
)
from backend.service.infrastructure.persistence.deployment_orm import (
    DeploymentRuntimeStateRecord,
)


class SqlAlchemyDeploymentRuntimeStateRepository:
    """使用 SQLAlchemy 持久化 deployment runtime state。"""

    def __init__(self, session: Session) -> None:
        """绑定当前事务 Session。"""

        self.session = session

    def save_deployment_runtime_state(self, state: DeploymentRuntimeState) -> None:
        """新增或更新一条 runtime state。"""

        try:
            record = self.session.get(
                DeploymentRuntimeStateRecord,
                (state.deployment_instance_id, state.runtime_mode),
            )
            if record is None:
                self.session.add(self._to_record(state))
                return
            for field_name in (
                "desired_state",
                "observed_state",
                "generation",
                "controller_owner_id",
                "controller_lease_expires_at",
                "process_id",
                "heartbeat_at",
                "restart_count",
                "consecutive_failure_count",
                "next_restart_at",
                "last_started_at",
                "last_stopped_at",
                "last_error_code",
                "last_error_message",
                "created_at",
                "updated_at",
            ):
                setattr(record, field_name, getattr(state, field_name))
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 Deployment runtime state 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_deployment_runtime_state(
        self,
        deployment_instance_id: str,
        runtime_mode: DeploymentRuntimeMode,
    ) -> DeploymentRuntimeState | None:
        """按 DeploymentInstance 和 runtime mode 读取状态。"""

        try:
            record = self.session.get(
                DeploymentRuntimeStateRecord,
                (deployment_instance_id, runtime_mode),
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 Deployment runtime state 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return None if record is None else self._to_domain(record)

    def try_save_deployment_runtime_state(
        self,
        state: DeploymentRuntimeState,
        *,
        expected_generation: int,
    ) -> bool:
        """使用 compare-and-swap 防止控制命令与状态回写相互覆盖。"""

        values = {
            field_name: getattr(state, field_name)
            for field_name in (
                "desired_state",
                "observed_state",
                "generation",
                "controller_owner_id",
                "controller_lease_expires_at",
                "process_id",
                "heartbeat_at",
                "restart_count",
                "consecutive_failure_count",
                "next_restart_at",
                "last_started_at",
                "last_stopped_at",
                "last_error_code",
                "last_error_message",
                "created_at",
                "updated_at",
            )
        }
        statement = (
            update(DeploymentRuntimeStateRecord)
            .where(
                DeploymentRuntimeStateRecord.deployment_instance_id
                == state.deployment_instance_id,
                DeploymentRuntimeStateRecord.runtime_mode == state.runtime_mode,
                DeploymentRuntimeStateRecord.generation == expected_generation,
            )
            .values(**values)
        )
        try:
            result = self.session.execute(statement)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "原子更新 Deployment runtime state 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return int(result.rowcount or 0) == 1

    def list_deployment_runtime_states(
        self,
        *,
        desired_state: str | None = None,
    ) -> tuple[DeploymentRuntimeState, ...]:
        """列出全部或指定期望状态的 runtime state。"""

        statement = select(DeploymentRuntimeStateRecord)
        if desired_state is not None:
            statement = statement.where(
                DeploymentRuntimeStateRecord.desired_state == desired_state
            )
        statement = statement.order_by(
            DeploymentRuntimeStateRecord.updated_at.asc(),
            DeploymentRuntimeStateRecord.deployment_instance_id.asc(),
            DeploymentRuntimeStateRecord.runtime_mode.asc(),
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 Deployment runtime state 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._to_domain(record) for record in records)

    def delete_deployment_runtime_states(self, deployment_instance_id: str) -> int:
        """删除指定 DeploymentInstance 的全部 runtime state。"""

        try:
            result = self.session.execute(
                delete(DeploymentRuntimeStateRecord).where(
                    DeploymentRuntimeStateRecord.deployment_instance_id
                    == deployment_instance_id
                )
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "删除 Deployment runtime state 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return int(result.rowcount or 0)

    def try_claim_deployment_runtime_state(
        self,
        *,
        deployment_instance_id: str,
        runtime_mode: DeploymentRuntimeMode,
        expected_generation: int,
        owner_id: str,
        now: str,
        lease_expires_at: str,
    ) -> bool:
        """使用单条条件更新领取 runtime state，避免重复 controller。"""

        statement = (
            update(DeploymentRuntimeStateRecord)
            .where(
                DeploymentRuntimeStateRecord.deployment_instance_id
                == deployment_instance_id,
                DeploymentRuntimeStateRecord.runtime_mode == runtime_mode,
                DeploymentRuntimeStateRecord.generation == expected_generation,
                or_(
                    DeploymentRuntimeStateRecord.controller_owner_id.is_(None),
                    DeploymentRuntimeStateRecord.controller_owner_id == owner_id,
                    DeploymentRuntimeStateRecord.controller_lease_expires_at.is_(None),
                    DeploymentRuntimeStateRecord.controller_lease_expires_at <= now,
                ),
            )
            .values(
                controller_owner_id=owner_id,
                controller_lease_expires_at=lease_expires_at,
                updated_at=now,
            )
        )
        try:
            result = self.session.execute(statement)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "领取 Deployment runtime state 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return int(result.rowcount or 0) == 1

    @staticmethod
    def _to_record(state: DeploymentRuntimeState) -> DeploymentRuntimeStateRecord:
        """把领域对象转换为 ORM 实体。"""

        return DeploymentRuntimeStateRecord(**state.__dict__)

    @staticmethod
    def _to_domain(record: DeploymentRuntimeStateRecord) -> DeploymentRuntimeState:
        """把 ORM 实体转换为领域对象。"""

        return DeploymentRuntimeState(
            deployment_instance_id=record.deployment_instance_id,
            runtime_mode=record.runtime_mode,  # type: ignore[arg-type]
            desired_state=record.desired_state,  # type: ignore[arg-type]
            observed_state=record.observed_state,  # type: ignore[arg-type]
            generation=record.generation,
            controller_owner_id=record.controller_owner_id,
            controller_lease_expires_at=record.controller_lease_expires_at,
            process_id=record.process_id,
            heartbeat_at=record.heartbeat_at,
            restart_count=record.restart_count,
            consecutive_failure_count=record.consecutive_failure_count,
            next_restart_at=record.next_restart_at,
            last_started_at=record.last_started_at,
            last_stopped_at=record.last_stopped_at,
            last_error_code=record.last_error_code,
            last_error_message=record.last_error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
