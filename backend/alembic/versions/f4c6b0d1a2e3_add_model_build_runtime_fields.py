"""add explicit model build runtime fields

Revision ID: f4c6b0d1a2e3
Revises: 8b1a7b1c2d3e
Create Date: 2026-07-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f4c6b0d1a2e3"
down_revision = "8b1a7b1c2d3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增 ModelBuild runtime 字段，并删除缺少明确字段的旧构建数据。"""

    op.add_column(
        "model_builds",
        sa.Column("runtime_backend", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "model_builds",
        sa.Column("runtime_precision", sa.String(length=32), nullable=True),
    )

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

    with op.batch_alter_table("model_builds") as batch_op:
        batch_op.alter_column(
            "runtime_backend",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.alter_column(
            "runtime_precision",
            existing_type=sa.String(length=32),
            nullable=False,
        )


def downgrade() -> None:
    """移除 ModelBuild runtime 字段。"""

    with op.batch_alter_table("model_builds") as batch_op:
        batch_op.drop_column("runtime_precision")
        batch_op.drop_column("runtime_backend")
