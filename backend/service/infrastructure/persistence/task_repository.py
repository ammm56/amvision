"""TaskRecord、TaskAttempt 与 TaskEvent 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.tasks.task_records import TaskAttempt, TaskEvent, TaskRecord
from backend.service.infrastructure.persistence.task_orm import (
    TaskAttemptEntity,
    TaskEventEntity,
    TaskRecordEntity,
)


class SqlAlchemyTaskRepository:
    """使用 SQLAlchemy 持久化通用任务记录。"""

    def __init__(self, session: Session) -> None:
        """初始化 Task 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_task(self, task_record: TaskRecord) -> None:
        """保存一个 TaskRecord。

        参数：
        - task_record：要保存的 TaskRecord。
        """

        try:
            existing_record = self.session.get(TaskRecordEntity, task_record.task_id)
            if existing_record is None:
                self.session.add(self._to_task_record_entity(task_record))
                return

            existing_record.task_kind = task_record.task_kind
            existing_record.display_name = task_record.display_name
            existing_record.project_id = task_record.project_id
            existing_record.created_by = task_record.created_by
            existing_record.created_at = task_record.created_at
            existing_record.parent_task_id = task_record.parent_task_id
            existing_record.task_spec_json = dict(task_record.task_spec)
            existing_record.resource_profile_id = task_record.resource_profile_id
            existing_record.worker_pool = task_record.worker_pool
            existing_record.metadata_json = dict(task_record.metadata)
            existing_record.state = task_record.state
            existing_record.current_attempt_no = task_record.current_attempt_no
            existing_record.started_at = task_record.started_at
            existing_record.finished_at = task_record.finished_at
            existing_record.progress_json = dict(task_record.progress)
            existing_record.result_json = dict(task_record.result)
            existing_record.error_message = task_record.error_message
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 TaskRecord 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_task(self, task_id: str) -> TaskRecord | None:
        """按 id 读取一个 TaskRecord。

        参数：
        - task_id：任务 id。

        返回：
        - 读取到的 TaskRecord；不存在时返回 None。
        """

        try:
            record = self.session.get(TaskRecordEntity, task_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 TaskRecord 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_task_record_domain(record)

    def list_tasks(self, project_id: str) -> tuple[TaskRecord, ...]:
        """按 Project id 列出任务记录。

        参数：
        - project_id：所属 Project id。

        返回：
        - 当前 Project 下的 TaskRecord 列表。
        """

        statement = (
            select(TaskRecordEntity)
            .where(TaskRecordEntity.project_id == project_id)
            .order_by(TaskRecordEntity.created_at, TaskRecordEntity.task_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 TaskRecord 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_task_record_domain(record) for record in records)

    def save_task_attempt(self, task_attempt: TaskAttempt) -> None:
        """保存一个 TaskAttempt。

        参数：
        - task_attempt：要保存的 TaskAttempt。
        """

        try:
            existing_record = self.session.get(TaskAttemptEntity, task_attempt.attempt_id)
            if existing_record is None:
                self.session.add(self._to_task_attempt_entity(task_attempt))
                return

            existing_record.task_id = task_attempt.task_id
            existing_record.attempt_no = task_attempt.attempt_no
            existing_record.worker_id = task_attempt.worker_id
            existing_record.host_id = task_attempt.host_id
            existing_record.process_id = task_attempt.process_id
            existing_record.state = task_attempt.state
            existing_record.started_at = task_attempt.started_at
            existing_record.heartbeat_at = task_attempt.heartbeat_at
            existing_record.ended_at = task_attempt.ended_at
            existing_record.exit_code = task_attempt.exit_code
            existing_record.result_json = dict(task_attempt.result)
            existing_record.error_message = task_attempt.error_message
            existing_record.metadata_json = dict(task_attempt.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 TaskAttempt 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_task_attempt(self, attempt_id: str) -> TaskAttempt | None:
        """按 id 读取一个 TaskAttempt。

        参数：
        - attempt_id：执行尝试 id。

        返回：
        - 读取到的 TaskAttempt；不存在时返回 None。
        """

        try:
            record = self.session.get(TaskAttemptEntity, attempt_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 TaskAttempt 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_task_attempt_domain(record)

    def list_task_attempts(self, task_id: str) -> tuple[TaskAttempt, ...]:
        """按 TaskRecord id 列出执行尝试。

        参数：
        - task_id：所属任务 id。

        返回：
        - 当前任务下的 TaskAttempt 列表。
        """

        statement = (
            select(TaskAttemptEntity)
            .where(TaskAttemptEntity.task_id == task_id)
            .order_by(TaskAttemptEntity.attempt_no, TaskAttemptEntity.attempt_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 TaskAttempt 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_task_attempt_domain(record) for record in records)

    def save_task_event(self, task_event: TaskEvent) -> None:
        """保存一个 TaskEvent。

        参数：
        - task_event：要保存的 TaskEvent。
        """

        try:
            existing_record = self.session.get(TaskEventEntity, task_event.event_id)
            if existing_record is None:
                self.session.add(self._to_task_event_entity(task_event))
                return

            existing_record.task_id = task_event.task_id
            existing_record.attempt_id = task_event.attempt_id
            existing_record.event_type = task_event.event_type
            existing_record.created_at = task_event.created_at
            existing_record.message = task_event.message
            existing_record.payload_json = dict(task_event.payload)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 TaskEvent 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_task_event(self, event_id: str) -> TaskEvent | None:
        """按 id 读取一个 TaskEvent。

        参数：
        - event_id：事件 id。

        返回：
        - 读取到的 TaskEvent；不存在时返回 None。
        """

        try:
            record = self.session.get(TaskEventEntity, event_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 TaskEvent 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_task_event_domain(record)

    def list_task_events(self, task_id: str) -> tuple[TaskEvent, ...]:
        """按 TaskRecord id 列出事件记录。

        参数：
        - task_id：所属任务 id。

        返回：
        - 当前任务下的 TaskEvent 列表。
        """

        statement = (
            select(TaskEventEntity)
            .where(TaskEventEntity.task_id == task_id)
            .order_by(TaskEventEntity.created_at, TaskEventEntity.event_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 TaskEvent 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_task_event_domain(record) for record in records)

    def _to_task_record_entity(self, task_record: TaskRecord) -> TaskRecordEntity:
        """把 TaskRecord 领域对象转换为 ORM 实体。"""

        return TaskRecordEntity(
            task_id=task_record.task_id,
            task_kind=task_record.task_kind,
            display_name=task_record.display_name,
            project_id=task_record.project_id,
            created_by=task_record.created_by,
            created_at=task_record.created_at,
            parent_task_id=task_record.parent_task_id,
            task_spec_json=dict(task_record.task_spec),
            resource_profile_id=task_record.resource_profile_id,
            worker_pool=task_record.worker_pool,
            metadata_json=dict(task_record.metadata),
            state=task_record.state,
            current_attempt_no=task_record.current_attempt_no,
            started_at=task_record.started_at,
            finished_at=task_record.finished_at,
            progress_json=dict(task_record.progress),
            result_json=dict(task_record.result),
            error_message=task_record.error_message,
        )

    def _to_task_attempt_entity(self, task_attempt: TaskAttempt) -> TaskAttemptEntity:
        """把 TaskAttempt 领域对象转换为 ORM 实体。"""

        return TaskAttemptEntity(
            attempt_id=task_attempt.attempt_id,
            task_id=task_attempt.task_id,
            attempt_no=task_attempt.attempt_no,
            worker_id=task_attempt.worker_id,
            host_id=task_attempt.host_id,
            process_id=task_attempt.process_id,
            state=task_attempt.state,
            started_at=task_attempt.started_at,
            heartbeat_at=task_attempt.heartbeat_at,
            ended_at=task_attempt.ended_at,
            exit_code=task_attempt.exit_code,
            result_json=dict(task_attempt.result),
            error_message=task_attempt.error_message,
            metadata_json=dict(task_attempt.metadata),
        )

    def _to_task_event_entity(self, task_event: TaskEvent) -> TaskEventEntity:
        """把 TaskEvent 领域对象转换为 ORM 实体。"""

        return TaskEventEntity(
            event_id=task_event.event_id,
            task_id=task_event.task_id,
            attempt_id=task_event.attempt_id,
            event_type=task_event.event_type,
            created_at=task_event.created_at,
            message=task_event.message,
            payload_json=dict(task_event.payload),
        )

    def _to_task_record_domain(self, record: TaskRecordEntity) -> TaskRecord:
        """把 ORM 实体转换为 TaskRecord 领域对象。"""

        return TaskRecord(
            task_id=record.task_id,
            task_kind=record.task_kind,
            project_id=record.project_id,
            display_name=record.display_name,
            created_by=record.created_by,
            created_at=record.created_at,
            parent_task_id=record.parent_task_id,
            task_spec=dict(record.task_spec_json or {}),
            resource_profile_id=record.resource_profile_id,
            worker_pool=record.worker_pool,
            metadata=dict(record.metadata_json or {}),
            state=record.state,
            current_attempt_no=record.current_attempt_no,
            started_at=record.started_at,
            finished_at=record.finished_at,
            progress=dict(record.progress_json or {}),
            result=dict(record.result_json or {}),
            error_message=record.error_message,
        )

    def _to_task_attempt_domain(self, record: TaskAttemptEntity) -> TaskAttempt:
        """把 ORM 实体转换为 TaskAttempt 领域对象。"""

        return TaskAttempt(
            attempt_id=record.attempt_id,
            task_id=record.task_id,
            attempt_no=record.attempt_no,
            worker_id=record.worker_id,
            host_id=record.host_id,
            process_id=record.process_id,
            state=record.state,
            started_at=record.started_at,
            heartbeat_at=record.heartbeat_at,
            ended_at=record.ended_at,
            exit_code=record.exit_code,
            result=dict(record.result_json or {}),
            error_message=record.error_message,
            metadata=dict(record.metadata_json or {}),
        )

    def _to_task_event_domain(self, record: TaskEventEntity) -> TaskEvent:
        """把 ORM 实体转换为 TaskEvent 领域对象。"""

        return TaskEvent(
            event_id=record.event_id,
            task_id=record.task_id,
            attempt_id=record.attempt_id,
            event_type=record.event_type,
            created_at=record.created_at,
            message=record.message,
            payload=dict(record.payload_json or {}),
        )