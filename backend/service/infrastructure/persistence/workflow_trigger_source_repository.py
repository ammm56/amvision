"""workflow trigger source 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.persistence.workflow_trigger_source_orm import (
    WorkflowTriggerSourceRecord,
)


class SqlAlchemyWorkflowTriggerSourceRepository:
    """使用 SQLAlchemy 持久化 WorkflowTriggerSource 资源。"""

    def __init__(self, session: Session) -> None:
        """初始化 WorkflowTriggerSource 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_trigger_source(self, trigger_source: WorkflowTriggerSource) -> None:
        """保存一条 WorkflowTriggerSource。"""

        try:
            existing_record = self.session.get(
                WorkflowTriggerSourceRecord, trigger_source.trigger_source_id
            )
            if existing_record is None:
                self.session.add(self._trigger_source_to_record(trigger_source))
                return

            existing_record.project_id = trigger_source.project_id
            existing_record.display_name = trigger_source.display_name
            existing_record.trigger_kind = trigger_source.trigger_kind
            existing_record.workflow_runtime_id = trigger_source.workflow_runtime_id
            existing_record.submit_mode = trigger_source.submit_mode
            existing_record.enabled = trigger_source.enabled
            existing_record.desired_state = trigger_source.desired_state
            existing_record.observed_state = trigger_source.observed_state
            existing_record.transport_config_json = dict(
                trigger_source.transport_config
            )
            existing_record.match_rule_json = dict(trigger_source.match_rule)
            existing_record.input_binding_mapping_json = dict(
                trigger_source.input_binding_mapping
            )
            existing_record.result_mapping_json = dict(trigger_source.result_mapping)
            existing_record.default_execution_metadata_json = dict(
                trigger_source.default_execution_metadata
            )
            existing_record.ack_policy = trigger_source.ack_policy
            existing_record.result_mode = trigger_source.result_mode
            existing_record.reply_timeout_seconds = trigger_source.reply_timeout_seconds
            existing_record.debounce_window_ms = trigger_source.debounce_window_ms
            existing_record.idempotency_key_path = trigger_source.idempotency_key_path
            existing_record.last_triggered_at = trigger_source.last_triggered_at
            existing_record.last_error = trigger_source.last_error
            existing_record.health_summary_json = dict(trigger_source.health_summary)
            existing_record.metadata_json = dict(trigger_source.metadata)
            existing_record.created_at = trigger_source.created_at
            existing_record.updated_at = trigger_source.updated_at
            existing_record.created_by = trigger_source.created_by
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 WorkflowTriggerSource 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_trigger_source(
        self, trigger_source_id: str
    ) -> WorkflowTriggerSource | None:
        """按 id 读取一条 WorkflowTriggerSource。"""

        try:
            record = self.session.get(WorkflowTriggerSourceRecord, trigger_source_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowTriggerSource 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None
        return self._trigger_source_to_domain(record)

    def list_trigger_sources(
        self, project_id: str
    ) -> tuple[WorkflowTriggerSource, ...]:
        """按 Project id 列出 WorkflowTriggerSource。"""

        statement = (
            select(WorkflowTriggerSourceRecord)
            .where(WorkflowTriggerSourceRecord.project_id == project_id)
            .order_by(
                WorkflowTriggerSourceRecord.created_at.desc(),
                WorkflowTriggerSourceRecord.trigger_source_id.desc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 WorkflowTriggerSource 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._trigger_source_to_domain(record) for record in records)

    def list_enabled_trigger_sources(self) -> tuple[WorkflowTriggerSource, ...]:
        """列出当前标记为 enabled 的 WorkflowTriggerSource。"""

        statement = (
            select(WorkflowTriggerSourceRecord)
            .where(WorkflowTriggerSourceRecord.enabled.is_(True))
            .order_by(
                WorkflowTriggerSourceRecord.created_at.asc(),
                WorkflowTriggerSourceRecord.trigger_source_id.asc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出已启用 WorkflowTriggerSource 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._trigger_source_to_domain(record) for record in records)

    def delete_trigger_source(self, trigger_source_id: str) -> bool:
        """按 id 删除一条 WorkflowTriggerSource。

        参数：
        - trigger_source_id：目标 TriggerSource id。

        返回：
        - bool：存在并已删除时返回 True；不存在时返回 False。
        """

        try:
            record = self.session.get(WorkflowTriggerSourceRecord, trigger_source_id)
            if record is None:
                return False
            self.session.delete(record)
            return True
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "删除 WorkflowTriggerSource 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    @staticmethod
    def _trigger_source_to_record(
        trigger_source: WorkflowTriggerSource,
    ) -> WorkflowTriggerSourceRecord:
        """把 WorkflowTriggerSource 转换为 ORM 实体。"""

        return WorkflowTriggerSourceRecord(
            trigger_source_id=trigger_source.trigger_source_id,
            project_id=trigger_source.project_id,
            display_name=trigger_source.display_name,
            trigger_kind=trigger_source.trigger_kind,
            workflow_runtime_id=trigger_source.workflow_runtime_id,
            submit_mode=trigger_source.submit_mode,
            enabled=trigger_source.enabled,
            desired_state=trigger_source.desired_state,
            observed_state=trigger_source.observed_state,
            transport_config_json=dict(trigger_source.transport_config),
            match_rule_json=dict(trigger_source.match_rule),
            input_binding_mapping_json=dict(trigger_source.input_binding_mapping),
            result_mapping_json=dict(trigger_source.result_mapping),
            default_execution_metadata_json=dict(
                trigger_source.default_execution_metadata
            ),
            ack_policy=trigger_source.ack_policy,
            result_mode=trigger_source.result_mode,
            reply_timeout_seconds=trigger_source.reply_timeout_seconds,
            debounce_window_ms=trigger_source.debounce_window_ms,
            idempotency_key_path=trigger_source.idempotency_key_path,
            last_triggered_at=trigger_source.last_triggered_at,
            last_error=trigger_source.last_error,
            health_summary_json=dict(trigger_source.health_summary),
            metadata_json=dict(trigger_source.metadata),
            created_at=trigger_source.created_at,
            updated_at=trigger_source.updated_at,
            created_by=trigger_source.created_by,
        )

    @staticmethod
    def _trigger_source_to_domain(
        record: WorkflowTriggerSourceRecord,
    ) -> WorkflowTriggerSource:
        """把 WorkflowTriggerSource ORM 实体转换为领域对象。"""

        return WorkflowTriggerSource(
            trigger_source_id=record.trigger_source_id,
            project_id=record.project_id,
            display_name=record.display_name,
            trigger_kind=record.trigger_kind,
            workflow_runtime_id=record.workflow_runtime_id,
            submit_mode=record.submit_mode,
            enabled=record.enabled,
            desired_state=record.desired_state,
            observed_state=record.observed_state,
            transport_config=dict(record.transport_config_json or {}),
            match_rule=dict(record.match_rule_json or {}),
            input_binding_mapping=dict(record.input_binding_mapping_json or {}),
            result_mapping=dict(record.result_mapping_json or {}),
            default_execution_metadata=dict(
                record.default_execution_metadata_json or {}
            ),
            ack_policy=record.ack_policy,
            result_mode=record.result_mode,
            reply_timeout_seconds=record.reply_timeout_seconds,
            debounce_window_ms=record.debounce_window_ms,
            idempotency_key_path=record.idempotency_key_path,
            last_triggered_at=record.last_triggered_at,
            last_error=record.last_error,
            health_summary=dict(record.health_summary_json or {}),
            metadata=dict(record.metadata_json or {}),
            created_at=record.created_at,
            updated_at=record.updated_at,
            created_by=record.created_by,
        )
