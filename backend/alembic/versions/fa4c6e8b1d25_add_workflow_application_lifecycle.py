"""add workflow application lifecycle CAS state

Revision ID: fa4c6e8b1d25
Revises: f9b3d5e7c2a4
Create Date: 2026-08-19 22:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.types import TypeEngine


revision = "fa4c6e8b1d25"
down_revision = "f9b3d5e7c2a4"
branch_labels = None
depends_on = None


_TABLE = "workflow_application_lifecycles"
_PRIMARY_KEY_COLUMNS = ("project_id", "application_id")
_INDEXES = {
    "ix_workflow_application_lifecycles_state": ("state",),
    "ix_workflow_application_lifecycles_updated_at": ("updated_at",),
}


def upgrade() -> None:
    """新增每个 Workflow Application 一行的持久化 CAS 状态门。"""

    inspector = inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        _validate_existing_table(inspector)
        _ensure_indexes(inspector)
        return
    op.create_table(
        _TABLE,
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("application_id", sa.String(length=128), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default="idle",
        ),
        sa.Column(
            "generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("operation_id", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
        sa.Column(
            "deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.PrimaryKeyConstraint(
            "project_id",
            "application_id",
            name="pk_workflow_application_lifecycles",
        ),
    )
    for index_name, column_names in _INDEXES.items():
        op.create_index(index_name, _TABLE, list(column_names))


def downgrade() -> None:
    """删除 Workflow Application lifecycle 状态门。"""

    if _TABLE not in inspect(op.get_bind()).get_table_names():
        return
    op.drop_table(_TABLE)


def _validate_existing_table(inspector: Inspector) -> None:
    """校验由当前 metadata 预建或由失败迁移遗留的同名表。"""

    columns = {str(item["name"]): item for item in inspector.get_columns(_TABLE)}
    expected_columns = {
        "project_id": (sa.String, 128, False),
        "application_id": (sa.String, 128, False),
        "state": (sa.String, 32, False),
        "generation": (sa.Integer, None, False),
        "operation_id": (sa.String, 128, True),
        "updated_at": (sa.String, 64, False),
    }
    missing = set(expected_columns) | {"deleted"}
    missing -= set(columns)
    if missing:
        raise RuntimeError(f"数据库表 {_TABLE} 缺少字段: {sorted(missing)!r}")

    for column_name, (
        type_class,
        expected_length,
        expected_nullable,
    ) in expected_columns.items():
        column = columns[column_name]
        column_type = column["type"]
        if not isinstance(column_type, type_class):
            raise RuntimeError(
                f"数据库表 {_TABLE}.{column_name} 类型不匹配: {column_type!r}"
            )
        if expected_length is not None and column_type.length != expected_length:
            raise RuntimeError(
                f"数据库表 {_TABLE}.{column_name} 长度不匹配: "
                f"actual={column_type.length!r}, expected={expected_length}"
            )
        if bool(column["nullable"]) is not expected_nullable:
            raise RuntimeError(
                f"数据库表 {_TABLE}.{column_name} nullable 不匹配: "
                f"actual={column['nullable']!r}, expected={expected_nullable}"
            )

    deleted_column = columns["deleted"]
    deleted_type = deleted_column["type"]
    if not _is_boolean_type(inspector, deleted_type):
        raise RuntimeError(f"数据库表 {_TABLE}.deleted 类型不匹配: {deleted_type!r}")
    if bool(deleted_column["nullable"]):
        raise RuntimeError(f"数据库表 {_TABLE}.deleted 必须为 NOT NULL")

    primary_key = inspector.get_pk_constraint(_TABLE)
    primary_key_columns = tuple(
        str(item) for item in primary_key.get("constrained_columns") or ()
    )
    if primary_key_columns != _PRIMARY_KEY_COLUMNS:
        raise RuntimeError(
            f"数据库表 {_TABLE} 主键不匹配: "
            f"actual={primary_key_columns!r}, expected={_PRIMARY_KEY_COLUMNS!r}"
        )


def _ensure_indexes(inspector: Inspector) -> None:
    """补齐 MySQL 非事务 DDL 中断后可能缺失的普通索引。"""

    existing_indexes = {
        str(item["name"]): item for item in inspector.get_indexes(_TABLE)
    }
    for index_name, expected_columns in _INDEXES.items():
        existing = existing_indexes.get(index_name)
        if existing is None:
            op.create_index(index_name, _TABLE, list(expected_columns))
            continue
        actual_columns = tuple(str(item) for item in existing.get("column_names") or ())
        if actual_columns != expected_columns or bool(existing.get("unique")):
            raise RuntimeError(
                f"数据库表 {_TABLE} 索引 {index_name} 不匹配: "
                f"columns={actual_columns!r}, unique={existing.get('unique')!r}"
            )


def _is_boolean_type(inspector: Inspector, column_type: TypeEngine) -> bool:
    """识别原生 Boolean 及 MySQL 对 BOOL 的 TINYINT(1) 反射形态。"""

    if isinstance(column_type, sa.Boolean):
        return True
    if inspector.bind.dialect.name != "mysql":
        return False
    return (
        type(column_type).__name__.upper() == "TINYINT"
        and getattr(column_type, "display_width", None) == 1
    )
