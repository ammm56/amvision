"""add task attempt claim uniqueness

Revision ID: c7a9e2d4f6b8
Revises: b6e4f1a8c2d7
Create Date: 2026-08-22 09:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Connection


revision = "c7a9e2d4f6b8"
down_revision = "b6e4f1a8c2d7"
branch_labels = None
depends_on = None


_TABLE = "task_attempts"
_CONSTRAINT = "uq_task_attempts_task_attempt_no"
_COLUMNS = ("task_id", "attempt_no")


def upgrade() -> None:
    """为持久任务消费 claim 增加跨数据库唯一约束。"""

    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError("task_attempts 表不存在，不能增加 worker claim 唯一约束")
    _reject_duplicate_attempts(bind)
    reflected_constraints = inspector.get_unique_constraints(_TABLE)
    existing_constraints = {
        str(item["name"]): tuple(item.get("column_names") or ())
        for item in reflected_constraints
        if item.get("name")
    }
    existing_columns = existing_constraints.get(_CONSTRAINT)
    if existing_columns is not None:
        if existing_columns != _COLUMNS:
            raise RuntimeError(
                f"{_CONSTRAINT} 字段不匹配；"
                f"期望 {_COLUMNS}，实际 {existing_columns}"
            )
        return
    if _COLUMNS in {
        tuple(item.get("column_names") or ()) for item in reflected_constraints
    }:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.create_unique_constraint(_CONSTRAINT, list(_COLUMNS))


def downgrade() -> None:
    """删除 TaskAttempt 消费 claim 唯一约束。"""

    inspector = inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    constraints = {
        str(item["name"]): tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints(_TABLE)
        if item.get("name")
    }
    if constraints.get(_CONSTRAINT) != _COLUMNS:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="unique")


def _reject_duplicate_attempts(bind: Connection) -> None:
    """拒绝静默删除历史重复 attempt，保留人工核对边界。"""

    attempts = sa.table(
        _TABLE,
        sa.column("task_id", sa.String()),
        sa.column("attempt_no", sa.Integer()),
    )
    duplicate = bind.execute(
        sa.select(attempts.c.task_id, attempts.c.attempt_no)
        .group_by(attempts.c.task_id, attempts.c.attempt_no)
        .having(sa.func.count() > 1)
        .limit(1)
    ).first()
    if duplicate is None:
        return
    raise RuntimeError(
        "task_attempts 存在重复的 (task_id, attempt_no)，"
        f"必须先人工核对: task_id={duplicate[0]!r}, attempt_no={duplicate[1]!r}"
    )
