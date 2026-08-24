"""add conversion publication reservation

Revision ID: d8e4f6a1b3c7
Revises: c7a9e2d4f6b8
Create Date: 2026-08-24 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Connection


revision = "d8e4f6a1b3c7"
down_revision = "c7a9e2d4f6b8"
branch_labels = None
depends_on = None


_TASKS_TABLE = "tasks"
_ATTEMPTS_TABLE = "task_attempts"
_OUTBOX_TABLE = "queue_outbox_messages"
_PUBLICATION_COLUMNS = (
    "publication_state",
    "publication_token",
    "publication_attempt_no",
    "publication_updated_at",
)
_PUBLICATION_INDEX = "ix_tasks_publication_recovery"
_PUBLICATION_CHECK = "ck_tasks_publication_fields_complete"
_CONVERSION_TASK_KINDS = (
    "yolox-conversion",
    "yolov8-conversion",
    "yolo11-conversion",
    "yolo26-conversion",
    "yolo-model-conversion",
    "rfdetr-conversion",
)


def upgrade() -> None:
    """确认旧协议已排空，再增加数据库 publication reservation。"""

    bind = op.get_bind()
    inspector = inspect(bind)
    if _TASKS_TABLE not in inspector.get_table_names():
        raise RuntimeError("tasks 表不存在，不能增加 publication reservation")
    existing_columns = {
        str(column["name"]) for column in inspector.get_columns(_TASKS_TABLE)
    }
    _reject_active_legacy_conversion_protocol(bind, inspector)
    present_publication_columns = existing_columns.intersection(_PUBLICATION_COLUMNS)
    if present_publication_columns:
        if present_publication_columns != set(_PUBLICATION_COLUMNS):
            raise RuntimeError(
                "tasks publication 字段只存在一部分，拒绝继续迁移: "
                + ", ".join(sorted(present_publication_columns))
            )
        _ensure_publication_index(inspect(bind))
        return

    with op.batch_alter_table(_TASKS_TABLE) as batch_op:
        batch_op.add_column(sa.Column("publication_state", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("publication_token", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("publication_attempt_no", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("publication_updated_at", sa.String(64), nullable=True)
        )
        batch_op.create_check_constraint(
            _PUBLICATION_CHECK,
            "(publication_state IS NULL AND publication_token IS NULL "
            "AND publication_attempt_no IS NULL AND publication_updated_at IS NULL) "
            "OR (publication_state IN ('reserved', 'published', 'registered', 'aborted') "
            "AND publication_token IS NOT NULL AND publication_attempt_no > 0 "
            "AND publication_updated_at IS NOT NULL)",
        )
    _ensure_publication_index(inspect(bind))


def downgrade() -> None:
    """删除 publication reservation 字段和约束。"""

    inspector = inspect(op.get_bind())
    if _TASKS_TABLE not in inspector.get_table_names():
        return
    indexes = {str(item["name"]) for item in inspector.get_indexes(_TASKS_TABLE)}
    if _PUBLICATION_INDEX in indexes:
        op.drop_index(_PUBLICATION_INDEX, table_name=_TASKS_TABLE)
    columns = {str(item["name"]) for item in inspector.get_columns(_TASKS_TABLE)}
    if not columns.intersection(_PUBLICATION_COLUMNS):
        return
    with op.batch_alter_table(_TASKS_TABLE) as batch_op:
        constraints = {
            str(item["name"])
            for item in inspector.get_check_constraints(_TASKS_TABLE)
            if item.get("name")
        }
        if _PUBLICATION_CHECK in constraints:
            batch_op.drop_constraint(_PUBLICATION_CHECK, type_="check")
        for column_name in reversed(_PUBLICATION_COLUMNS):
            if column_name in columns:
                batch_op.drop_column(column_name)


def _ensure_publication_index(inspector: sa.Inspector) -> None:
    """幂等建立 recovery 扫描索引。"""

    indexes = {
        str(item["name"]): tuple(item.get("column_names") or ())
        for item in inspector.get_indexes(_TASKS_TABLE)
        if item.get("name")
    }
    expected = ("publication_state", "publication_updated_at")
    existing = indexes.get(_PUBLICATION_INDEX)
    if existing is not None:
        if existing != expected:
            raise RuntimeError(
                f"{_PUBLICATION_INDEX} 字段不匹配；期望 {expected}，实际 {existing}"
            )
        return
    op.create_index(_PUBLICATION_INDEX, _TASKS_TABLE, list(expected), unique=False)


def _reject_active_legacy_conversion_protocol(
    bind: Connection,
    inspector: sa.Inspector,
) -> None:
    """DDL 前拒绝旧协议仍有活动 Conversion，避免维护双写兼容路径。"""

    tasks = sa.table(
        _TASKS_TABLE,
        sa.column("task_id", sa.String()),
        sa.column("task_kind", sa.String()),
        sa.column("state", sa.String()),
    )
    all_conversion_task_ids = set(
        bind.execute(
            sa.select(tasks.c.task_id).where(
                tasks.c.task_kind.in_(_CONVERSION_TASK_KINDS)
            )
        ).scalars()
    )
    active_task_ids = tuple(
        bind.execute(
            sa.select(tasks.c.task_id)
            .where(
                tasks.c.task_kind.in_(_CONVERSION_TASK_KINDS),
                tasks.c.state.in_(("queued", "running")),
            )
            .limit(20)
        ).scalars()
    )

    active_attempt_ids: tuple[str, ...] = ()
    if _ATTEMPTS_TABLE in inspector.get_table_names():
        attempts = sa.table(
            _ATTEMPTS_TABLE,
            sa.column("attempt_id", sa.String()),
            sa.column("task_id", sa.String()),
            sa.column("state", sa.String()),
        )
        active_attempt_ids = tuple(
            bind.execute(
                sa.select(attempts.c.attempt_id)
                .where(
                    attempts.c.task_id.in_(all_conversion_task_ids),
                    attempts.c.state == "running",
                )
                .limit(20)
            ).scalars()
        )

    active_outbox_ids: list[str] = []
    if _OUTBOX_TABLE in inspector.get_table_names():
        outbox = sa.table(
            _OUTBOX_TABLE,
            sa.column("message_id", sa.String()),
            sa.column("payload_json", sa.JSON()),
            sa.column("state", sa.String()),
        )
        for message_id, payload in bind.execute(
            sa.select(outbox.c.message_id, outbox.c.payload_json).where(
                outbox.c.state.in_(("pending", "leased"))
            )
        ):
            normalized_payload = payload if isinstance(payload, dict) else {}
            if (
                normalized_payload.get("task_id") in all_conversion_task_ids
                or normalized_payload.get("task_kind") in _CONVERSION_TASK_KINDS
            ):
                active_outbox_ids.append(str(message_id))
                if len(active_outbox_ids) >= 20:
                    break

    if not active_task_ids and not active_attempt_ids and not active_outbox_ids:
        return
    raise RuntimeError(
        "检测到旧协议的活动 Conversion，必须停止 Worker 并排空后再升级；"
        f"tasks={list(active_task_ids)}, attempts={list(active_attempt_ids)}, "
        f"outbox={active_outbox_ids}"
    )
