"""harden workflow app publish content deduplication

Revision ID: f8a2c4e6b1d3
Revises: f7d1e3a5b9c2
Create Date: 2026-08-19 20:10:00.000000
"""

from __future__ import annotations

from collections import defaultdict

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f8a2c4e6b1d3"
down_revision = "f7d1e3a5b9c2"
branch_labels = None
depends_on = None


_TABLE = "workflow_app_versions"
_DEDUPLICATION_COLUMN = "content_deduplication_key"
_DEDUPLICATION_CONSTRAINT = "uq_workflow_app_version_content_deduplication"
_DEDUPLICATION_COLUMNS = (
    "project_id",
    "application_id",
    _DEDUPLICATION_COLUMN,
)


def upgrade() -> None:
    """增加跨数据库唯一内容占位，并从现有版本选择一条规范占位。"""

    inspector = inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError(f"数据库缺少数据表: {_TABLE}")
    columns = {str(item["name"]) for item in inspector.get_columns(_TABLE)}
    if _DEDUPLICATION_COLUMN not in columns:
        op.add_column(
            _TABLE,
            sa.Column(_DEDUPLICATION_COLUMN, sa.String(length=256), nullable=True),
        )

    _backfill_content_deduplication_keys()
    if not _has_deduplication_constraint():
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.create_unique_constraint(
                _DEDUPLICATION_CONSTRAINT,
                list(_DEDUPLICATION_COLUMNS),
            )


def downgrade() -> None:
    """删除发布内容占位约束和内部字段。"""

    inspector = inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError(f"数据库缺少数据表: {_TABLE}")
    constraint_name = _find_deduplication_constraint_name()
    columns = {str(item["name"]) for item in inspector.get_columns(_TABLE)}
    if constraint_name is not None or _DEDUPLICATION_COLUMN in columns:
        with op.batch_alter_table(_TABLE) as batch_op:
            if constraint_name is not None:
                batch_op.drop_constraint(constraint_name, type_="unique")
            if _DEDUPLICATION_COLUMN in columns:
                batch_op.drop_column(_DEDUPLICATION_COLUMN)


def _backfill_content_deduplication_keys() -> None:
    """每组内容只保留一条非 failed 规范版本持有默认去重键。"""

    connection = op.get_bind()
    version_table = sa.table(
        _TABLE,
        sa.column("workflow_app_version_id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("application_id", sa.String()),
        sa.column("version_number", sa.Integer()),
        sa.column("content_fingerprint", sa.String()),
        sa.column("state", sa.String()),
        sa.column(_DEDUPLICATION_COLUMN, sa.String()),
    )
    rows = connection.execute(
        sa.select(
            version_table.c.workflow_app_version_id,
            version_table.c.project_id,
            version_table.c.application_id,
            version_table.c.version_number,
            version_table.c.content_fingerprint,
            version_table.c.state,
        )
    ).mappings()
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        state = str(row["state"])
        fingerprint = str(row["content_fingerprint"])
        if state == "failed" or not fingerprint:
            continue
        grouped[
            (
                str(row["project_id"]),
                str(row["application_id"]),
                fingerprint,
            )
        ].append(dict(row))

    # 迁移可重复执行：先清空旧占位，再按确定性顺序重建。
    connection.execute(sa.update(version_table).values({_DEDUPLICATION_COLUMN: None}))
    state_priority = {"published": 0, "archived": 1, "publishing": 2}
    for (_project_id, _application_id, fingerprint), candidates in grouped.items():
        selected = min(
            candidates,
            key=lambda item: (
                state_priority.get(str(item["state"]), 3),
                -int(item["version_number"]),
                str(item["workflow_app_version_id"]),
            ),
        )
        connection.execute(
            sa.update(version_table)
            .where(
                version_table.c.workflow_app_version_id
                == str(selected["workflow_app_version_id"])
            )
            .values({_DEDUPLICATION_COLUMN: fingerprint})
        )


def _has_deduplication_constraint() -> bool:
    """判断目标列组合是否已经受唯一约束保护。"""

    return _find_deduplication_constraint_name() is not None


def _find_deduplication_constraint_name() -> str | None:
    """按字段签名查找内容去重唯一约束。"""

    inspector = inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(_TABLE):
        if _column_signature(constraint.get("column_names")) != _DEDUPLICATION_COLUMNS:
            continue
        name = constraint.get("name")
        if not name:
            raise RuntimeError("Workflow App 内容去重唯一约束缺少名称")
        return str(name)
    return None


def _column_signature(value: object) -> tuple[str, ...]:
    """把 Inspector 字段集合规范为稳定签名。"""

    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)
