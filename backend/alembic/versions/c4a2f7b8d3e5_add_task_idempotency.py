"""add task idempotency

Revision ID: c4a2f7b8d3e5
Revises: b3f1e6a9c2d4
Create Date: 2026-08-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "c4a2f7b8d3e5"
down_revision = "b3f1e6a9c2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加任务幂等键、请求指纹及查重约束。"""

    inspector = inspect(op.get_bind())
    columns = {row["name"] for row in inspector.get_columns("tasks")}
    with op.batch_alter_table("tasks") as batch_op:
        if "idempotency_key" not in columns:
            batch_op.add_column(
                sa.Column("idempotency_key", sa.String(128), nullable=True)
            )
        if "request_fingerprint" not in columns:
            batch_op.add_column(
                sa.Column("request_fingerprint", sa.String(64), nullable=True)
            )

    inspector = inspect(op.get_bind())
    uniques = {
        row["name"]
        for row in inspector.get_unique_constraints("tasks")
        if row.get("name")
    }
    if "uq_tasks_project_kind_idempotency" not in uniques:
        with op.batch_alter_table("tasks") as batch_op:
            batch_op.create_unique_constraint(
                "uq_tasks_project_kind_idempotency",
                ["project_id", "task_kind", "idempotency_key"],
            )

    indexes = {
        row["name"] for row in inspect(op.get_bind()).get_indexes("tasks")
    }
    if "ix_tasks_idempotency_lookup" not in indexes:
        op.create_index(
            "ix_tasks_idempotency_lookup",
            "tasks",
            ["project_id", "task_kind", "idempotency_key"],
        )


def downgrade() -> None:
    """移除任务幂等字段和约束。"""

    indexes = {
        row["name"] for row in inspect(op.get_bind()).get_indexes("tasks")
    }
    if "ix_tasks_idempotency_lookup" in indexes:
        op.drop_index("ix_tasks_idempotency_lookup", table_name="tasks")
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint(
            "uq_tasks_project_kind_idempotency",
            type_="unique",
        )
        batch_op.drop_column("request_fingerprint")
        batch_op.drop_column("idempotency_key")
