"""add explicit model build runtime fields

Revision ID: f4c6b0d1a2e3
Revises: 8b1a7b1c2d3e
Create Date: 2026-07-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f4c6b0d1a2e3"
down_revision = "8b1a7b1c2d3e"
branch_labels = None
depends_on = None

_MODEL_BUILDS_TABLE = "model_builds"
_RUNTIME_COLUMNS = (
    "runtime_backend",
    "runtime_precision",
)


def _table_columns() -> dict[str, dict[str, object]]:
    """读取 ModelBuild 表字段，支持初始迁移已创建最新 schema 的情况。"""
    bind = op.get_bind()
    return {
        column["name"]: column
        for column in inspect(bind).get_columns(_MODEL_BUILDS_TABLE)
    }


def _add_missing_runtime_columns(columns: dict[str, dict[str, object]]) -> None:
    """仅在旧库缺少字段时补充 runtime 字段。"""
    if "runtime_backend" not in columns:
        op.add_column(
            _MODEL_BUILDS_TABLE,
            sa.Column("runtime_backend", sa.String(length=64), nullable=True),
        )
    if "runtime_precision" not in columns:
        op.add_column(
            _MODEL_BUILDS_TABLE,
            sa.Column("runtime_precision", sa.String(length=32), nullable=True),
        )


def _require_runtime_columns(columns: dict[str, dict[str, object]]) -> None:
    """把 runtime 字段收紧为必填。"""
    nullable_columns = [
        name
        for name in _RUNTIME_COLUMNS
        if name in columns and columns[name]["nullable"]
    ]
    if not nullable_columns:
        return
    with op.batch_alter_table(_MODEL_BUILDS_TABLE) as batch_op:
        if "runtime_backend" in nullable_columns:
            batch_op.alter_column(
                "runtime_backend",
                existing_type=sa.String(length=64),
                nullable=False,
            )
        if "runtime_precision" in nullable_columns:
            batch_op.alter_column(
                "runtime_precision",
                existing_type=sa.String(length=32),
                nullable=False,
            )


def upgrade() -> None:
    """新增 ModelBuild runtime 字段，并删除缺少明确字段的旧构建数据。"""

    columns = _table_columns()
    _add_missing_runtime_columns(columns)

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            DELETE FROM model_files
            WHERE model_build_id IN (
                SELECT model_build_id
                FROM model_builds
                WHERE runtime_backend IS NULL OR runtime_precision IS NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM model_builds
            WHERE runtime_backend IS NULL OR runtime_precision IS NULL
            """
        )
    )

    columns = _table_columns()
    _require_runtime_columns(columns)


def downgrade() -> None:
    """移除 ModelBuild runtime 字段。"""

    columns = _table_columns()
    existing_runtime_columns = [name for name in _RUNTIME_COLUMNS if name in columns]
    if existing_runtime_columns:
        with op.batch_alter_table(_MODEL_BUILDS_TABLE) as batch_op:
            for name in reversed(_RUNTIME_COLUMNS):
                if name in existing_runtime_columns:
                    batch_op.drop_column(name)
