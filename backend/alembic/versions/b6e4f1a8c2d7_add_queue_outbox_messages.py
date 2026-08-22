"""add transactional queue outbox messages

Revision ID: b6e4f1a8c2d7
Revises: fa4c6e8b1d25
Create Date: 2026-08-20 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b6e4f1a8c2d7"
down_revision = "fa4c6e8b1d25"
branch_labels = None
depends_on = None


_TABLE = "queue_outbox_messages"
_REQUIRED_COLUMNS = {
    "message_id",
    "queue_name",
    "payload_json",
    "metadata_json",
    "payload_fingerprint",
    "state",
    "created_at",
    "available_at",
    "lease_owner",
    "lease_expires_at",
    "dispatched_at",
    "attempt_count",
    "last_error",
}
_INDEXES = {
    "ix_queue_outbox_dispatch_scan": (
        "state",
        "available_at",
        "lease_expires_at",
        "created_at",
    ),
    "ix_queue_outbox_messages_queue_name": ("queue_name",),
    "ix_queue_outbox_messages_state": ("state",),
    "ix_queue_outbox_messages_created_at": ("created_at",),
    "ix_queue_outbox_messages_available_at": ("available_at",),
}


def upgrade() -> None:
    """新增跨 SQLite、MySQL 和 PostgreSQL 的 Outbox 表与领取索引。"""

    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE in inspector.get_table_names():
        _validate_existing_table(inspector)
        _ensure_indexes(inspector)
        return
    op.create_table(
        _TABLE,
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("queue_name", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("available_at", sa.String(length=64), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.String(length=64), nullable=True),
        sa.Column("dispatched_at", sa.String(length=64), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error", sa.String(length=2048), nullable=True),
        sa.PrimaryKeyConstraint("message_id", name="pk_queue_outbox_messages"),
    )
    _ensure_indexes(inspect(bind))


def downgrade() -> None:
    """删除 Transactional Outbox 表。"""

    if _TABLE in inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)


def _validate_existing_table(inspector: sa.Inspector) -> None:
    """拒绝把缺列或主键错误的既有表静默视为已完成迁移。"""

    columns = {item["name"] for item in inspector.get_columns(_TABLE)}
    missing = sorted(_REQUIRED_COLUMNS - columns)
    if missing:
        raise RuntimeError(
            "queue_outbox_messages 表结构不完整，缺少字段: " + ", ".join(missing)
        )
    primary_key = inspector.get_pk_constraint(_TABLE)
    if tuple(primary_key.get("constrained_columns") or ()) != ("message_id",):
        raise RuntimeError("queue_outbox_messages 主键必须为 message_id")


def _ensure_indexes(inspector: sa.Inspector) -> None:
    """补齐缺失索引，并拒绝同名错列索引。"""

    existing = {
        str(item["name"]): tuple(item.get("column_names") or ())
        for item in inspector.get_indexes(_TABLE)
        if item.get("name")
    }
    for name, columns in _INDEXES.items():
        actual_columns = existing.get(name)
        if actual_columns is None:
            op.create_index(name, _TABLE, list(columns))
            continue
        if actual_columns != columns:
            raise RuntimeError(
                f"queue_outbox_messages 索引 {name} 字段不匹配；"
                f"期望 {columns}，实际 {actual_columns}"
            )
