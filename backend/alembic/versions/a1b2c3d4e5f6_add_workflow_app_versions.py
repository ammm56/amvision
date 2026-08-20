"""add workflow app versions and runtime revisions

Revision ID: a1b2c3d4e5f6
Revises: c4a2f7b8d3e5
Create Date: 2026-08-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "a1b2c3d4e5f6"
down_revision = "c4a2f7b8d3e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加不可变 App Version、Runtime revision 和运行来源字段。"""

    inspector = inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "workflow_app_versions" not in table_names:
        op.create_table(
            "workflow_app_versions",
            sa.Column("workflow_app_version_id", sa.String(length=128), nullable=False),
            sa.Column("project_id", sa.String(length=128), nullable=False),
            sa.Column("application_id", sa.String(length=128), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("display_version", sa.String(length=128), nullable=False),
            sa.Column("release_notes", sa.String(length=4096), nullable=False, server_default=""),
            sa.Column("application_snapshot_object_key", sa.String(length=1024), nullable=False),
            sa.Column("template_snapshot_object_key", sa.String(length=1024), nullable=False),
            sa.Column("contract_snapshot_object_key", sa.String(length=1024), nullable=False),
            sa.Column("dependency_manifest_object_key", sa.String(length=1024), nullable=False),
            sa.Column("content_fingerprint", sa.String(length=256), nullable=False),
            sa.Column("contract_fingerprint", sa.String(length=256), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.String(length=64), nullable=False),
            sa.Column("created_by", sa.String(length=128), nullable=True),
            sa.Column("completed_at", sa.String(length=64), nullable=True),
            sa.Column("error", sa.String(length=2048), nullable=True),
            sa.PrimaryKeyConstraint("workflow_app_version_id"),
            sa.UniqueConstraint(
                "project_id",
                "application_id",
                "version_number",
                name="uq_workflow_app_version_number",
            ),
        )
        for column in (
            "project_id",
            "application_id",
            "content_fingerprint",
            "contract_fingerprint",
            "state",
            "created_at",
        ):
            op.create_index(
                f"ix_workflow_app_versions_{column}",
                "workflow_app_versions",
                [column],
            )

    _add_columns_if_missing(
        "workflow_app_runtimes",
        (
            sa.Column("active_revision_id", sa.String(length=128), nullable=True),
            sa.Column("desired_revision_id", sa.String(length=128), nullable=True),
            sa.Column(
                "revision_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        ),
    )
    _add_columns_if_missing(
        "workflow_runs",
        (
            sa.Column("workflow_runtime_revision_id", sa.String(length=128), nullable=True),
            sa.Column("workflow_app_version_id", sa.String(length=128), nullable=True),
            sa.Column("runtime_generation", sa.Integer(), nullable=True),
            sa.Column("snapshot_fingerprint", sa.String(length=256), nullable=True),
        ),
    )

    table_names = set(inspect(op.get_bind()).get_table_names())
    if "workflow_runtime_revisions" not in table_names:
        op.create_table(
            "workflow_runtime_revisions",
            sa.Column("workflow_runtime_revision_id", sa.String(length=128), nullable=False),
            sa.Column("workflow_runtime_id", sa.String(length=128), nullable=False),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.Column("workflow_app_version_id", sa.String(length=128), nullable=False),
            sa.Column("execution_policy_snapshot_object_key", sa.String(length=1024), nullable=True),
            sa.Column("expected_snapshot_fingerprint", sa.String(length=256), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.String(length=64), nullable=False),
            sa.Column("activated_at", sa.String(length=64), nullable=True),
            sa.Column("failed_at", sa.String(length=64), nullable=True),
            sa.Column("error", sa.String(length=2048), nullable=True),
            sa.Column("created_by", sa.String(length=128), nullable=True),
            sa.ForeignKeyConstraint(
                ["workflow_runtime_id"],
                ["workflow_app_runtimes.workflow_runtime_id"],
                name="fk_workflow_runtime_revisions_runtime",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["workflow_app_version_id"],
                ["workflow_app_versions.workflow_app_version_id"],
                name="fk_workflow_runtime_revisions_app_version",
            ),
            sa.PrimaryKeyConstraint("workflow_runtime_revision_id"),
            sa.UniqueConstraint(
                "workflow_runtime_id",
                "generation",
                name="uq_workflow_runtime_revision_generation",
            ),
        )
        for column in (
            "workflow_runtime_id",
            "workflow_app_version_id",
            "state",
            "created_at",
        ):
            op.create_index(
                f"ix_workflow_runtime_revisions_{column}",
                "workflow_runtime_revisions",
                [column],
            )
    else:
        _ensure_runtime_revision_foreign_keys()


def downgrade() -> None:
    """移除版本管理字段和表。"""

    table_names = set(inspect(op.get_bind()).get_table_names())
    if "workflow_runtime_revisions" in table_names:
        op.drop_table("workflow_runtime_revisions")
    _drop_columns_if_present(
        "workflow_runs",
        (
            "snapshot_fingerprint",
            "runtime_generation",
            "workflow_app_version_id",
            "workflow_runtime_revision_id",
        ),
    )
    _drop_columns_if_present(
        "workflow_app_runtimes",
        ("revision_generation", "desired_revision_id", "active_revision_id"),
    )
    table_names = set(inspect(op.get_bind()).get_table_names())
    if "workflow_app_versions" in table_names:
        op.drop_table("workflow_app_versions")


def _ensure_runtime_revision_foreign_keys() -> None:
    """为旧 ``create_all`` 表补齐 Runtime revision 外键。"""

    inspector = inspect(op.get_bind())
    required_columns = {
        "workflow_runtime_revisions": {
            "workflow_runtime_id",
            "workflow_app_version_id",
        },
        "workflow_app_runtimes": {"workflow_runtime_id"},
        "workflow_app_versions": {"workflow_app_version_id"},
    }
    table_names = set(inspector.get_table_names())
    for table_name, column_names in required_columns.items():
        if table_name not in table_names:
            raise RuntimeError(f"Workflow 版本迁移缺少数据表: {table_name}")
        existing_columns = {
            str(item["name"]) for item in inspector.get_columns(table_name)
        }
        missing_columns = column_names - existing_columns
        if missing_columns:
            raise RuntimeError(
                f"Workflow 版本迁移数据表 {table_name} 缺少字段: "
                f"{sorted(missing_columns)!r}"
            )

    existing_foreign_keys = {
        (
            tuple(item.get("constrained_columns") or ()),
            item.get("referred_table"),
            tuple(item.get("referred_columns") or ()),
        ): _normalize_foreign_key_action(
            (item.get("options") or {}).get("ondelete")
        )
        for item in inspector.get_foreign_keys("workflow_runtime_revisions")
    }
    required = (
        (
            "fk_workflow_runtime_revisions_runtime",
            ("workflow_runtime_id",),
            "workflow_app_runtimes",
            ("workflow_runtime_id",),
            "CASCADE",
        ),
        (
            "fk_workflow_runtime_revisions_app_version",
            ("workflow_app_version_id",),
            "workflow_app_versions",
            ("workflow_app_version_id",),
            None,
        ),
    )
    missing = []
    for item in required:
        mapping = (item[1], item[2], item[3])
        if mapping not in existing_foreign_keys:
            missing.append(item)
            continue
        actual_action = existing_foreign_keys[mapping]
        if actual_action != item[4]:
            raise RuntimeError(
                f"Workflow Runtime revision 外键 {item[0]} 的 ondelete 不匹配；"
                f"期望 {item[4]!r}，实际 {actual_action!r}"
            )
    if not missing:
        return

    _reject_orphan_runtime_revisions(missing)
    with op.batch_alter_table("workflow_runtime_revisions") as batch_op:
        for name, local_columns, remote_table, remote_columns, ondelete in missing:
            batch_op.create_foreign_key(
                name,
                remote_table,
                list(local_columns),
                list(remote_columns),
                ondelete=ondelete,
            )


def _normalize_foreign_key_action(value: object) -> str | None:
    """把数据库返回的默认 NO ACTION 统一为空动作。"""

    normalized = str(value or "").strip().upper()
    return None if normalized in {"", "NO ACTION"} else normalized


def _reject_orphan_runtime_revisions(
    missing: list[tuple[str, tuple[str, ...], str, tuple[str, ...], str | None]],
) -> None:
    """补外键前拒绝孤儿 revision，避免迁移静默删除生产数据。"""

    connection = op.get_bind()
    missing_names = {item[0] for item in missing}
    checks = (
        (
            "fk_workflow_runtime_revisions_runtime",
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
            "fk_workflow_runtime_revisions_app_version",
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
    for constraint_name, statement, field_name in checks:
        if constraint_name not in missing_names:
            continue
        orphan_count = int(connection.execute(sa.text(statement)).scalar_one())
        if orphan_count:
            raise RuntimeError(
                "workflow_runtime_revisions 存在无法关联父记录的数据，"
                f"不能补齐 {field_name} 外键；孤儿记录数：{orphan_count}"
            )


def _add_columns_if_missing(table_name: str, columns: tuple[sa.Column, ...]) -> None:
    """以 SQLite 兼容方式增加缺失字段。"""

    existing = {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}
    with op.batch_alter_table(table_name) as batch_op:
        for column in columns:
            if column.name not in existing:
                batch_op.add_column(column)


def _drop_columns_if_present(table_name: str, column_names: tuple[str, ...]) -> None:
    """以 SQLite 兼容方式删除存在字段。"""

    existing = {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}
    with op.batch_alter_table(table_name) as batch_op:
        for column_name in column_names:
            if column_name in existing:
                batch_op.drop_column(column_name)
