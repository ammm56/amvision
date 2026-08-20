"""add workflow run worker epoch provenance

Revision ID: f9b3d5e7c2a4
Revises: f8a2c4e6b1d3
Create Date: 2026-08-19 21:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f9b3d5e7c2a4"
down_revision = "f8a2c4e6b1d3"
branch_labels = None
depends_on = None


_TABLE = "workflow_runs"
_COLUMN = "worker_instance_id"


def upgrade() -> None:
    """为 WorkflowRun 增加实际调用 worker epoch 来源字段。"""

    inspector = inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError(f"数据库缺少数据表: {_TABLE}")
    columns = {str(item["name"]) for item in inspector.get_columns(_TABLE)}
    if _COLUMN in columns:
        return
    # nullable VARCHAR 可在 SQLite、MySQL 和 PostgreSQL 直接新增；历史 Run
    # 保持 NULL，不能根据 Runtime 当前 worker 反向猜测来源。
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    """删除 WorkflowRun worker epoch 来源字段。"""

    inspector = inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError(f"数据库缺少数据表: {_TABLE}")
    columns = {str(item["name"]) for item in inspector.get_columns(_TABLE)}
    if _COLUMN not in columns:
        return
    # batch 模式兼容 SQLite 的 DROP COLUMN，同时适用于 MySQL/PostgreSQL。
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
