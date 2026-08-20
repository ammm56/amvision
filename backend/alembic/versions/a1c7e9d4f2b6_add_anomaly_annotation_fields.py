"""add anomaly annotation fields

Revision ID: a1c7e9d4f2b6
Revises: e7a4c1d9b2f0
Create Date: 2026-08-12 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "a1c7e9d4f2b6"
down_revision = "e7a4c1d9b2f0"
branch_labels = None
depends_on = None

_TABLE = "dataset_detection_annotations"
_ANOMALY_COLUMNS = ("is_anomalous", "mask_file_name")


def _table_columns() -> dict[str, dict[str, object]]:
    """读取统一 annotation 表的字段元数据。"""

    return {
        str(column["name"]): column
        for column in inspect(op.get_bind()).get_columns(_TABLE)
    }


def upgrade() -> None:
    """增加 anomaly 标记和 mask 文件名，并允许 anomaly 不绑定类别。"""

    columns = _table_columns()
    if "is_anomalous" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("is_anomalous", sa.Boolean(), nullable=True),
        )
    if "mask_file_name" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("mask_file_name", sa.String(length=512), nullable=True),
        )

    columns = _table_columns()
    category_column = columns.get("category_id")
    if category_column is None:
        raise RuntimeError(f"{_TABLE} 缺少 category_id")
    if not bool(category_column["nullable"]):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.alter_column(
                "category_id",
                existing_type=sa.Integer(),
                nullable=True,
            )


def downgrade() -> None:
    """删除 anomaly 数据和字段，并恢复 category_id 非空约束。"""

    columns = _table_columns()
    if "annotation_type" in columns:
        op.execute(
            sa.text(
                "DELETE FROM dataset_detection_annotations "
                "WHERE annotation_type = 'anomaly'"
            )
        )
    op.execute(
        sa.text(
            "DELETE FROM dataset_detection_annotations WHERE category_id IS NULL"
        )
    )

    columns = _table_columns()
    category_column = columns.get("category_id")
    if category_column is not None and bool(category_column["nullable"]):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.alter_column(
                "category_id",
                existing_type=sa.Integer(),
                nullable=False,
            )

    columns = _table_columns()
    existing_columns = [name for name in _ANOMALY_COLUMNS if name in columns]
    if existing_columns:
        with op.batch_alter_table(_TABLE) as batch_op:
            for name in reversed(_ANOMALY_COLUMNS):
                if name in existing_columns:
                    batch_op.drop_column(name)
