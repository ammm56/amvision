"""Task runtime 协议升级前的旧 schema 只读预检。"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import inspect

from backend.service.application.conversions.task_kinds import CONVERSION_TASK_KINDS
from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings, get_backend_service_settings


VERIFY_TASK_RUNTIME_UPGRADE_COMMAND = "verify-task-runtime-upgrade"


@dataclass(frozen=True)
class TaskRuntimeUpgradeBlockers:
    """描述旧协议中仍未排空的 Conversion 执行记录。"""

    task_ids: tuple[str, ...] = ()
    attempt_ids: tuple[str, ...] = ()
    outbox_message_ids: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        """返回是否不存在任何升级阻塞项。"""

        return not (self.task_ids or self.attempt_ids or self.outbox_message_ids)


def verify_task_runtime_upgrade(
    *,
    backend_service_settings: BackendServiceSettings | None = None,
) -> dict[str, object]:
    """只读取旧 schema 已有列，确认旧 Conversion 协议已经排空。"""

    settings = backend_service_settings or get_backend_service_settings()
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        blockers = _find_upgrade_blockers(session_factory.engine)
    finally:
        session_factory.engine.dispose()
    if not blockers.empty:
        raise ServiceConfigurationError(
            "Task runtime 升级预检失败：旧协议 Conversion 尚未排空",
            details={
                "task_ids": list(blockers.task_ids),
                "attempt_ids": list(blockers.attempt_ids),
                "outbox_message_ids": list(blockers.outbox_message_ids),
            },
        )
    return {
        "command": VERIFY_TASK_RUNTIME_UPGRADE_COMMAND,
        "ready": True,
        "conversion_task_kinds": list(CONVERSION_TASK_KINDS),
        "active_task_ids": [],
        "active_attempt_ids": [],
        "active_outbox_message_ids": [],
    }


def _find_upgrade_blockers(engine: sa.Engine) -> TaskRuntimeUpgradeBlockers:
    """通过 SQLAlchemy Core/reflection 查询旧 schema，不构造当前 Task ORM。"""

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "tasks" not in table_names:
        raise ServiceConfigurationError("Task runtime 升级预检找不到 tasks 表")
    task_columns = {str(item["name"]) for item in inspector.get_columns("tasks")}
    required_task_columns = {"task_id", "task_kind", "state"}
    if not required_task_columns.issubset(task_columns):
        raise ServiceConfigurationError(
            "Task runtime 升级预检发现 tasks 旧 schema 不完整",
            details={"missing_columns": sorted(required_task_columns - task_columns)},
        )

    metadata = sa.MetaData()
    tasks = sa.Table("tasks", metadata, autoload_with=engine)
    with engine.connect() as connection:
        all_conversion_task_ids = set(
            str(value)
            for value in connection.execute(
                sa.select(tasks.c.task_id).where(
                    tasks.c.task_kind.in_(CONVERSION_TASK_KINDS)
                )
            ).scalars()
        )
        active_task_ids = tuple(
            str(value)
            for value in connection.execute(
                sa.select(tasks.c.task_id)
                .where(
                    tasks.c.task_kind.in_(CONVERSION_TASK_KINDS),
                    tasks.c.state.in_(("queued", "running")),
                )
                .order_by(tasks.c.task_id)
                .limit(100)
            ).scalars()
        )
        active_attempt_ids = _find_active_attempt_ids(
            connection=connection,
            metadata=metadata,
            table_names=table_names,
            conversion_task_ids=all_conversion_task_ids,
        )
        active_outbox_ids = _find_active_outbox_ids(
            connection=connection,
            metadata=metadata,
            table_names=table_names,
            conversion_task_ids=all_conversion_task_ids,
        )
    return TaskRuntimeUpgradeBlockers(
        task_ids=active_task_ids,
        attempt_ids=active_attempt_ids,
        outbox_message_ids=active_outbox_ids,
    )


def _find_active_attempt_ids(
    *,
    connection: sa.Connection,
    metadata: sa.MetaData,
    table_names: set[str],
    conversion_task_ids: set[str],
) -> tuple[str, ...]:
    """读取旧 schema 中 running Conversion Attempt。"""

    if "task_attempts" not in table_names or not conversion_task_ids:
        return ()
    attempts = sa.Table("task_attempts", metadata, autoload_with=connection)
    return tuple(
        str(value)
        for value in connection.execute(
            sa.select(attempts.c.attempt_id)
            .where(
                attempts.c.task_id.in_(conversion_task_ids),
                attempts.c.state == "running",
            )
            .order_by(attempts.c.attempt_id)
            .limit(100)
        ).scalars()
    )


def _find_active_outbox_ids(
    *,
    connection: sa.Connection,
    metadata: sa.MetaData,
    table_names: set[str],
    conversion_task_ids: set[str],
) -> tuple[str, ...]:
    """读取未完成且归属于 Conversion 的旧 Outbox 消息。"""

    if "queue_outbox_messages" not in table_names:
        return ()
    outbox = sa.Table("queue_outbox_messages", metadata, autoload_with=connection)
    message_ids: list[str] = []
    rows = connection.execute(
        sa.select(outbox.c.message_id, outbox.c.payload_json)
        .where(outbox.c.state.in_(("pending", "leased")))
        .order_by(outbox.c.message_id)
    )
    for message_id, payload in rows:
        normalized = payload if isinstance(payload, dict) else {}
        if (
            normalized.get("task_id") in conversion_task_ids
            or normalized.get("task_kind") in CONVERSION_TASK_KINDS
        ):
            message_ids.append(str(message_id))
            if len(message_ids) >= 100:
                break
    return tuple(message_ids)


__all__ = [
    "TaskRuntimeUpgradeBlockers",
    "VERIFY_TASK_RUNTIME_UPGRADE_COMMAND",
    "verify_task_runtime_upgrade",
]
