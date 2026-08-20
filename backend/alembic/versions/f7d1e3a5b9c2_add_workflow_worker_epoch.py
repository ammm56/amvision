"""add workflow worker epoch and reconcile model version indexes

Revision ID: f7d1e3a5b9c2
Revises: e6c9b2d4f8a1
Create Date: 2026-08-19 19:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine.reflection import Inspector


revision = "f7d1e3a5b9c2"
down_revision = "e6c9b2d4f8a1"
branch_labels = None
depends_on = None


_MODEL_VERSION_TABLE = "model_versions"
_TRAINING_TASK_COLUMN = "training_task_id"
_TRAINING_TASK_INDEX = "ix_model_versions_training_task_id"
_RUNTIME_TABLE = "workflow_app_runtimes"
_WORKER_INSTANCE_COLUMN = "worker_instance_id"


def upgrade() -> None:
    """增加 worker epoch，并清理漂移库残留的训练任务唯一索引。"""

    inspector = inspect(op.get_bind())
    _require_column(
        inspector,
        table_name=_MODEL_VERSION_TABLE,
        column_name=_TRAINING_TASK_COLUMN,
    )
    _require_table(inspector, _RUNTIME_TABLE)

    runtime_columns = {
        str(item["name"]) for item in inspector.get_columns(_RUNTIME_TABLE)
    }
    if _WORKER_INSTANCE_COLUMN not in runtime_columns:
        # nullable 字段可直接 ADD COLUMN，避免 SQLite 为一次简单新增重建整张
        # Runtime 表；PostgreSQL 和 MySQL 也使用相同语义。
        op.add_column(
            _RUNTIME_TABLE,
            sa.Column(_WORKER_INSTANCE_COLUMN, sa.String(length=128), nullable=True),
        )

    _drop_training_task_uniqueness()
    refreshed = inspect(op.get_bind())
    indexes = {
        str(item["name"]): bool(item.get("unique"))
        for item in refreshed.get_indexes(_MODEL_VERSION_TABLE)
    }
    if indexes.get(_TRAINING_TASK_INDEX) is True:
        op.drop_index(_TRAINING_TASK_INDEX, table_name=_MODEL_VERSION_TABLE)
        indexes.pop(_TRAINING_TASK_INDEX, None)
    if _TRAINING_TASK_INDEX not in indexes:
        op.create_index(
            _TRAINING_TASK_INDEX,
            _MODEL_VERSION_TABLE,
            [_TRAINING_TASK_COLUMN],
            unique=False,
        )


def downgrade() -> None:
    """删除 worker epoch；训练任务多版本能力属于前序 revision，保持不变。"""

    inspector = inspect(op.get_bind())
    if _RUNTIME_TABLE not in inspector.get_table_names():
        raise RuntimeError(f"数据库缺少数据表: {_RUNTIME_TABLE}")
    runtime_columns = {
        str(item["name"]) for item in inspector.get_columns(_RUNTIME_TABLE)
    }
    if _WORKER_INSTANCE_COLUMN in runtime_columns:
        with op.batch_alter_table(_RUNTIME_TABLE) as batch_op:
            batch_op.drop_column(_WORKER_INSTANCE_COLUMN)


def _drop_training_task_uniqueness() -> None:
    """同时清理唯一约束和独立 unique index 两种历史漂移形态。"""

    inspector = inspect(op.get_bind())
    constraints = [
        item
        for item in inspector.get_unique_constraints(_MODEL_VERSION_TABLE)
        if _column_signature(item.get("column_names")) == (_TRAINING_TASK_COLUMN,)
    ]
    constraint_names: list[str] = []
    for constraint in constraints:
        constraint_name = constraint.get("name")
        if not constraint_name:
            raise RuntimeError(
                "model_versions.training_task_id 存在未命名唯一约束，无法安全删除"
            )
        constraint_names.append(str(constraint_name))

    if constraint_names:
        with op.batch_alter_table(_MODEL_VERSION_TABLE) as batch_op:
            for constraint_name in constraint_names:
                batch_op.drop_constraint(constraint_name, type_="unique")

    inspector = inspect(op.get_bind())
    unique_indexes = [
        item
        for item in inspector.get_indexes(_MODEL_VERSION_TABLE)
        if bool(item.get("unique"))
        and _column_signature(item.get("column_names")) == (_TRAINING_TASK_COLUMN,)
    ]
    for index in unique_indexes:
        index_name = index.get("name")
        if not index_name:
            raise RuntimeError(
                "model_versions.training_task_id 存在未命名 unique index，"
                "无法安全删除"
            )
        op.drop_index(str(index_name), table_name=_MODEL_VERSION_TABLE)


def _column_signature(value: object) -> tuple[str, ...]:
    """把 Inspector 返回的字段集合规范为可比较签名。"""

    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)


def _require_table(inspector: Inspector, table_name: str) -> None:
    """确认迁移依赖的数据表存在。"""

    if table_name not in inspector.get_table_names():
        raise RuntimeError(f"数据库缺少数据表: {table_name}")


def _require_column(
    inspector: Inspector,
    *,
    table_name: str,
    column_name: str,
) -> None:
    """确认迁移依赖的数据表和字段存在。"""

    _require_table(inspector, table_name)
    column_names = {
        str(item["name"]) for item in inspector.get_columns(table_name)
    }
    if column_name not in column_names:
        raise RuntimeError(f"数据库表 {table_name} 缺少字段: {column_name}")
