"""replace deployment runtime configuration

Revision ID: c9d8e7f6a5b4
Revises: f4c6b0d1a2e3
Create Date: 2026-07-23
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c9d8e7f6a5b4"
down_revision: str | None = "f4c6b0d1a2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """删除旧部署数据并切换到完整运行时配置结构。"""

    column_names = _deployment_column_names()
    if "runtime_configuration_json" in column_names:
        if "instance_count" in column_names:
            raise RuntimeError("deployment_instances 同时存在新旧运行时配置列")
        return
    if "instance_count" not in column_names:
        raise RuntimeError("deployment_instances 缺少可迁移的 instance_count 列")

    op.execute(sa.text("DELETE FROM deployment_instances"))
    with op.batch_alter_table("deployment_instances") as batch_op:
        batch_op.drop_column("instance_count")
        batch_op.add_column(
            sa.Column("runtime_configuration_json", sa.JSON(), nullable=False)
        )


def downgrade() -> None:
    """恢复旧列；部署记录不会恢复。"""

    column_names = _deployment_column_names()
    if "instance_count" in column_names:
        if "runtime_configuration_json" in column_names:
            raise RuntimeError("deployment_instances 同时存在新旧运行时配置列")
        return
    if "runtime_configuration_json" not in column_names:
        raise RuntimeError("deployment_instances 缺少可降级的 runtime_configuration_json 列")

    op.execute(sa.text("DELETE FROM deployment_instances"))
    with op.batch_alter_table("deployment_instances") as batch_op:
        batch_op.drop_column("runtime_configuration_json")
        batch_op.add_column(
            sa.Column("instance_count", sa.Integer(), nullable=False, server_default="1")
        )


def _deployment_column_names() -> set[str]:
    """读取 deployment_instances 当前列集合。"""

    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns("deployment_instances")
    }
