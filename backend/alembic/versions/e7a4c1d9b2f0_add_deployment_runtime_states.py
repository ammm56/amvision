"""add deployment runtime states

Revision ID: e7a4c1d9b2f0
Revises: c9d8e7f6a5b4
Create Date: 2026-08-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "e7a4c1d9b2f0"
down_revision = "c9d8e7f6a5b4"
branch_labels = None
depends_on = None

_TABLE = "deployment_runtime_states"


def upgrade() -> None:
    """创建 deployment runtime state 表；历史 Deployment 默认保持 stopped。"""

    if _TABLE in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("deployment_instance_id", sa.String(length=128), nullable=False),
        sa.Column("runtime_mode", sa.String(length=16), nullable=False),
        sa.Column("desired_state", sa.String(length=16), nullable=False),
        sa.Column("observed_state", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("controller_owner_id", sa.String(length=128), nullable=True),
        sa.Column("controller_lease_expires_at", sa.String(length=64), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("heartbeat_at", sa.String(length=64), nullable=True),
        sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_restart_at", sa.String(length=64), nullable=True),
        sa.Column("last_started_at", sa.String(length=64), nullable=True),
        sa.Column("last_stopped_at", sa.String(length=64), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_message", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_instance_id"],
            ["deployment_instances.deployment_instance_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("deployment_instance_id", "runtime_mode"),
        sa.UniqueConstraint(
            "deployment_instance_id",
            "runtime_mode",
            name="uq_deployment_runtime_state_instance_mode",
        ),
    )
    for column in (
        "desired_state",
        "observed_state",
        "controller_lease_expires_at",
        "next_restart_at",
        "created_at",
        "updated_at",
    ):
        op.create_index(f"ix_{_TABLE}_{column}", _TABLE, [column])


def downgrade() -> None:
    """删除 deployment runtime state 表。"""

    if _TABLE in inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
