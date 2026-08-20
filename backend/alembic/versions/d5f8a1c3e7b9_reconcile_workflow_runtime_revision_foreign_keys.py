"""reconcile workflow runtime revision foreign keys

Revision ID: d5f8a1c3e7b9
Revises: a1b2c3d4e5f6
Create Date: 2026-08-19 10:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine.reflection import Inspector


revision = "d5f8a1c3e7b9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


_RUNTIME_FOREIGN_KEY = (
    "fk_workflow_runtime_revisions_runtime",
    ("workflow_runtime_id",),
    "workflow_app_runtimes",
    ("workflow_runtime_id",),
    "CASCADE",
)
_APP_VERSION_FOREIGN_KEY = (
    "fk_workflow_runtime_revisions_app_version",
    ("workflow_app_version_id",),
    "workflow_app_versions",
    ("workflow_app_version_id",),
    None,
)


def upgrade() -> None:
    """原地补齐旧 ``create_all`` 表缺失的两条父记录外键。"""

    inspector = inspect(op.get_bind())
    _require_schema(inspector)
    existing = _read_foreign_keys(inspector)
    missing = []
    for expected in (_RUNTIME_FOREIGN_KEY, _APP_VERSION_FOREIGN_KEY):
        name, local_columns, remote_table, remote_columns, ondelete = expected
        mapping = (local_columns, remote_table, remote_columns)
        matches = [item for item in existing if item[:3] == mapping]
        if len(matches) > 1:
            raise RuntimeError(f"Workflow Runtime revision 存在重复外键: {name}")
        if not matches:
            missing.append(expected)
            continue
        if matches[0][3] != ondelete:
            raise RuntimeError(
                f"Workflow Runtime revision 外键 {name} 的 ondelete 不匹配；"
                f"期望 {ondelete!r}，实际 {matches[0][3]!r}"
            )

    if not missing:
        return

    _reject_orphans(missing)
    with op.batch_alter_table("workflow_runtime_revisions") as batch_op:
        for name, local_columns, remote_table, remote_columns, ondelete in missing:
            batch_op.create_foreign_key(
                name,
                remote_table,
                list(local_columns),
                list(remote_columns),
                ondelete=ondelete,
            )


def downgrade() -> None:
    """保留外键；它们属于前序 a1b2 revision 的既定 schema。"""

    # 本 revision 只修复 a1b2 已声明但旧 create_all 路径遗漏的约束。
    # 无法可靠区分约束最初由哪个 revision 创建，回退时删除会破坏正确的
    # a1b2 schema；继续回退到 c4a2 时，a1b2 downgrade 会删除整个子表。


def _require_schema(inspector: Inspector) -> None:
    """确认修复所需的父子表和关键字段完整存在。"""

    required = {
        "workflow_runtime_revisions": {
            "workflow_runtime_id",
            "workflow_app_version_id",
        },
        "workflow_app_runtimes": {"workflow_runtime_id"},
        "workflow_app_versions": {"workflow_app_version_id"},
    }
    table_names = set(inspector.get_table_names())
    for table_name, column_names in required.items():
        if table_name not in table_names:
            raise RuntimeError(f"Workflow 版本数据库缺少数据表: {table_name}")
        existing_columns = {
            str(item["name"]) for item in inspector.get_columns(table_name)
        }
        missing_columns = column_names - existing_columns
        if missing_columns:
            raise RuntimeError(
                f"Workflow 版本数据表 {table_name} 缺少字段: "
                f"{sorted(missing_columns)!r}"
            )


def _read_foreign_keys(
    inspector: Inspector,
) -> list[tuple[tuple[str, ...], str, tuple[str, ...], str | None]]:
    """读取外键逻辑签名，不依赖约束名称。"""

    return [
        (
            tuple(str(value) for value in item.get("constrained_columns") or ()),
            str(item["referred_table"]),
            tuple(str(value) for value in item.get("referred_columns") or ()),
            _normalize_action((item.get("options") or {}).get("ondelete")),
        )
        for item in inspector.get_foreign_keys("workflow_runtime_revisions")
    ]


def _normalize_action(value: object) -> str | None:
    """把数据库返回的默认 NO ACTION 统一为空动作。"""

    normalized = str(value or "").strip().upper()
    return None if normalized in {"", "NO ACTION"} else normalized


def _reject_orphans(
    missing: list[
        tuple[str, tuple[str, ...], str, tuple[str, ...], str | None]
    ],
) -> None:
    """补外键前拒绝孤儿 revision，不静默修改或删除生产数据。"""

    missing_names = {item[0] for item in missing}
    checks = (
        (
            _RUNTIME_FOREIGN_KEY[0],
            """
            SELECT COUNT(*)
            FROM workflow_runtime_revisions AS revision
            LEFT JOIN workflow_app_runtimes AS runtime
              ON runtime.workflow_runtime_id = revision.workflow_runtime_id
            WHERE runtime.workflow_runtime_id IS NULL
            """,
            "workflow_runtime_id",
        ),
        (
            _APP_VERSION_FOREIGN_KEY[0],
            """
            SELECT COUNT(*)
            FROM workflow_runtime_revisions AS revision
            LEFT JOIN workflow_app_versions AS app_version
              ON app_version.workflow_app_version_id = revision.workflow_app_version_id
            WHERE app_version.workflow_app_version_id IS NULL
            """,
            "workflow_app_version_id",
        ),
    )
    connection = op.get_bind()
    for constraint_name, statement, field_name in checks:
        if constraint_name not in missing_names:
            continue
        orphan_count = int(connection.execute(sa.text(statement)).scalar_one())
        if orphan_count:
            raise RuntimeError(
                "workflow_runtime_revisions 存在无法关联父记录的数据，"
                f"不能补齐 {field_name} 外键；孤儿记录数：{orphan_count}"
            )
