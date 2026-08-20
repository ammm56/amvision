"""allow multiple model versions per training task

Revision ID: e6c9b2d4f8a1
Revises: d5f8a1c3e7b9
Create Date: 2026-08-19 18:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine.reflection import Inspector


revision = "e6c9b2d4f8a1"
down_revision = "d5f8a1c3e7b9"
branch_labels = None
depends_on = None


_TABLE_NAME = "model_versions"
_COLUMN_NAME = "training_task_id"
_CONSTRAINT_NAME = "uq_model_versions_training_task"


def upgrade() -> None:
    """允许同一训练任务登记 latest、best 和手动 checkpoint 等多个版本。"""

    inspector = inspect(op.get_bind())
    _require_training_task_column(inspector)
    matching_constraints = _training_task_unique_constraints(inspector)
    if len(matching_constraints) > 1:
        raise RuntimeError(
            "model_versions.training_task_id 存在重复唯一约束，无法安全迁移"
        )
    if not matching_constraints:
        return

    constraint_name = matching_constraints[0].get("name")
    if not constraint_name:
        raise RuntimeError(
            "model_versions.training_task_id 存在未命名唯一约束，无法安全删除"
        )
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_constraint(str(constraint_name), type_="unique")


def downgrade() -> None:
    """仅在没有多版本训练数据时恢复历史唯一约束。"""

    inspector = inspect(op.get_bind())
    _require_training_task_column(inspector)
    matching_constraints = _training_task_unique_constraints(inspector)
    if len(matching_constraints) > 1:
        raise RuntimeError(
            "model_versions.training_task_id 存在重复唯一约束，无法安全回退"
        )
    if matching_constraints:
        return

    duplicate = op.get_bind().execute(
        sa.text(
            "SELECT training_task_id, COUNT(*) AS version_count "
            "FROM model_versions "
            "WHERE training_task_id IS NOT NULL "
            "GROUP BY training_task_id "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "model_versions 已包含同一训练任务的多个版本，不能恢复历史唯一约束；"
            f"training_task_id={duplicate[0]!r}, version_count={duplicate[1]}"
        )

    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.create_unique_constraint(
            _CONSTRAINT_NAME,
            [_COLUMN_NAME],
        )


def _require_training_task_column(inspector: Inspector) -> None:
    """确认目标表和训练任务字段存在，避免静默掩盖 schema 损坏。"""

    if _TABLE_NAME not in inspector.get_table_names():
        raise RuntimeError(f"模型版本数据库缺少数据表: {_TABLE_NAME}")
    columns = {str(item["name"]) for item in inspector.get_columns(_TABLE_NAME)}
    if _COLUMN_NAME not in columns:
        raise RuntimeError(
            f"模型版本数据表 {_TABLE_NAME} 缺少字段: {_COLUMN_NAME}"
        )


def _training_task_unique_constraints(
    inspector: Inspector,
) -> list[dict[str, object]]:
    """按字段逻辑签名读取训练任务唯一约束，不依赖历史名称。"""

    return [
        item
        for item in inspector.get_unique_constraints(_TABLE_NAME)
        if tuple(str(value) for value in item.get("column_names") or ())
        == (_COLUMN_NAME,)
    ]
