"""Workflow App 版本迁移的跨数据库方言门禁。"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy import inspect, text

from backend.maintenance.database_migrations import _build_alembic_config
from backend.alembic.versions.fa4c6e8b1d25_add_workflow_application_lifecycle import (
    _is_boolean_type,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowApplicationLifecycleRecord,
    WorkflowAppRuntimeRecord,
    WorkflowAppVersionRecord,
    WorkflowRunRecord,
    WorkflowRuntimeRevisionRecord,
)
from backend.service.settings import BackendServiceSettings


_LIFECYCLE_TABLE = "workflow_application_lifecycles"
_LIFECYCLE_STATE_INDEX = "ix_workflow_application_lifecycles_state"
_LIFECYCLE_UPDATED_AT_INDEX = "ix_workflow_application_lifecycles_updated_at"


def test_workflow_version_migration_chain_has_one_head() -> None:
    """验证 f7-f8-f9-fa 串行且 Alembic 只有一个 head。"""

    settings = BackendServiceSettings(
        database={"url": "sqlite:///:memory:", "echo": False}
    )
    script = ScriptDirectory.from_config(_build_alembic_config(settings))

    assert tuple(script.get_heads()) == ("fa4c6e8b1d25",)
    assert script.get_revision("f8a2c4e6b1d3").down_revision == "f7d1e3a5b9c2"
    assert script.get_revision("f9b3d5e7c2a4").down_revision == "f8a2c4e6b1d3"
    assert script.get_revision("fa4c6e8b1d25").down_revision == "f9b3d5e7c2a4"


def test_lifecycle_boolean_validation_only_accepts_mysql_tinyint_one() -> None:
    """验证 MySQL Boolean 反射兼容不会放宽到任意整数。"""

    mysql_inspector = SimpleNamespace(
        bind=SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    )
    postgresql_inspector = SimpleNamespace(
        bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )

    assert _is_boolean_type(mysql_inspector, mysql.TINYINT(display_width=1))
    assert not _is_boolean_type(mysql_inspector, mysql.TINYINT())
    assert not _is_boolean_type(mysql_inspector, mysql.INTEGER())
    assert _is_boolean_type(postgresql_inspector, sa.Boolean())
    assert not _is_boolean_type(postgresql_inspector, sa.Integer())


@pytest.mark.parametrize(
    ("database_url", "drop_unique_fragment", "drop_index_fragment"),
    (
        (
            "mysql://",
            "DROP INDEX uq_workflow_app_version_content_deduplication",
            "DROP INDEX ux_model_versions_training_task_drift ON model_versions",
        ),
        (
            "postgresql://",
            "DROP CONSTRAINT uq_workflow_app_version_content_deduplication",
            "DROP INDEX ux_model_versions_training_task_drift",
        ),
    ),
)
def test_workflow_version_ddl_compiles_for_supported_server_dialects(
    database_url: str,
    drop_unique_fragment: str,
    drop_index_fragment: str,
) -> None:
    """验证 f7 至 fa 使用的 DDL 可由 MySQL/PostgreSQL 方言编译。"""

    statement = _compile_workflow_version_ddl(database_url)

    assert "ADD COLUMN worker_instance_id VARCHAR(128)" in statement
    assert "ADD COLUMN content_deduplication_key VARCHAR(256)" in statement
    assert (
        "CONSTRAINT uq_workflow_app_version_content_deduplication UNIQUE "
        "(project_id, application_id, content_deduplication_key)" in statement
    )
    assert "CONSTRAINT fk_workflow_runtime_revisions_runtime FOREIGN KEY" in statement
    assert (
        "CONSTRAINT fk_workflow_runtime_revisions_app_version FOREIGN KEY" in statement
    )
    assert (
        "CONSTRAINT pk_workflow_application_lifecycles PRIMARY KEY "
        "(project_id, application_id)" in statement
    )
    assert "deleted BOOL NOT NULL DEFAULT false" in statement or (
        "deleted BOOLEAN DEFAULT false NOT NULL" in statement
    )
    assert drop_unique_fragment in statement
    assert drop_index_fragment in statement


def test_current_metadata_matches_workflow_version_migration_contracts() -> None:
    """验证 initial metadata 路径与后续版本迁移保持同一 schema。"""

    runtime_worker = WorkflowAppRuntimeRecord.__table__.c.worker_instance_id
    run_worker = WorkflowRunRecord.__table__.c.worker_instance_id
    assert runtime_worker.nullable is True
    assert run_worker.nullable is True
    assert runtime_worker.type.length == 128
    assert run_worker.type.length == 128

    app_version_table = WorkflowAppVersionRecord.__table__
    deduplication_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in app_version_table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert deduplication_constraints[
        "uq_workflow_app_version_content_deduplication"
    ] == (
        "project_id",
        "application_id",
        "content_deduplication_key",
    )
    assert app_version_table.c.content_deduplication_key.nullable is True

    revision_table = WorkflowRuntimeRevisionRecord.__table__
    foreign_keys = {
        constraint.name: (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in revision_table.foreign_key_constraints
    }
    assert foreign_keys["fk_workflow_runtime_revisions_runtime"] == (
        ("workflow_runtime_id",),
        ("workflow_app_runtimes.workflow_runtime_id",),
        "CASCADE",
    )
    assert foreign_keys["fk_workflow_runtime_revisions_app_version"] == (
        ("workflow_app_version_id",),
        ("workflow_app_versions.workflow_app_version_id",),
        None,
    )

    lifecycle_table = WorkflowApplicationLifecycleRecord.__table__
    assert tuple(column.name for column in lifecycle_table.primary_key.columns) == (
        "project_id",
        "application_id",
    )
    assert {_LIFECYCLE_STATE_INDEX, _LIFECYCLE_UPDATED_AT_INDEX} <= {
        str(index.name) for index in lifecycle_table.indexes
    }


def test_lifecycle_migration_recovers_missing_index_after_interrupted_ddl(
    tmp_path: Path,
) -> None:
    """验证 fa 可补齐 MySQL 非事务 DDL 中断时可能遗漏的索引。"""

    settings = _sqlite_settings(tmp_path / "fa-missing-index.db")
    config = _build_alembic_config(settings)
    command.upgrade(config, "f9b3d5e7c2a4")
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        with session_factory.engine.begin() as connection:
            connection.execute(text(f"DROP INDEX {_LIFECYCLE_STATE_INDEX}"))
        assert _LIFECYCLE_STATE_INDEX not in {
            str(item["name"])
            for item in inspect(session_factory.engine).get_indexes(_LIFECYCLE_TABLE)
        }
    finally:
        session_factory.engine.dispose()

    command.upgrade(config, "head")
    verification_factory = SessionFactory(settings.to_database_settings())
    try:
        indexes = {
            str(item["name"]): tuple(item.get("column_names") or ())
            for item in inspect(verification_factory.engine).get_indexes(
                _LIFECYCLE_TABLE
            )
        }
        assert indexes[_LIFECYCLE_STATE_INDEX] == ("state",)
        assert indexes[_LIFECYCLE_UPDATED_AT_INDEX] == ("updated_at",)
    finally:
        verification_factory.engine.dispose()


def test_lifecycle_migration_rejects_conflicting_named_index(
    tmp_path: Path,
) -> None:
    """验证同名错列索引不会被静默接受并标记为 head。"""

    settings = _sqlite_settings(tmp_path / "fa-conflicting-index.db")
    config = _build_alembic_config(settings)
    command.upgrade(config, "f9b3d5e7c2a4")
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        with session_factory.engine.begin() as connection:
            connection.execute(text(f"DROP INDEX {_LIFECYCLE_STATE_INDEX}"))
            connection.execute(
                text(
                    f"CREATE INDEX {_LIFECYCLE_STATE_INDEX} "
                    f"ON {_LIFECYCLE_TABLE} (generation)"
                )
            )
    finally:
        session_factory.engine.dispose()

    with pytest.raises(RuntimeError, match="索引.*不匹配"):
        command.upgrade(config, "head")

    verification_factory = SessionFactory(settings.to_database_settings())
    try:
        with verification_factory.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == "f9b3d5e7c2a4"
    finally:
        verification_factory.engine.dispose()


def _compile_workflow_version_ddl(database_url: str) -> str:
    """离线编译 f7 至 fa 的跨数据库 DDL 原语。"""

    output = StringIO()
    context = MigrationContext.configure(
        url=database_url,
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)

    operations.add_column(
        "workflow_app_runtimes",
        sa.Column("worker_instance_id", sa.String(length=128), nullable=True),
    )
    with operations.batch_alter_table("model_versions") as batch_op:
        batch_op.drop_constraint(
            "uq_model_versions_training_task",
            type_="unique",
        )
    operations.drop_index(
        "ux_model_versions_training_task_drift",
        table_name="model_versions",
    )
    operations.create_index(
        "ix_model_versions_training_task_id",
        "model_versions",
        ["training_task_id"],
        unique=False,
    )
    with operations.batch_alter_table("workflow_app_versions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "content_deduplication_key",
                sa.String(length=256),
                nullable=True,
            )
        )
        batch_op.create_unique_constraint(
            "uq_workflow_app_version_content_deduplication",
            ["project_id", "application_id", "content_deduplication_key"],
        )
    operations.add_column(
        "workflow_runs",
        sa.Column("worker_instance_id", sa.String(length=128), nullable=True),
    )
    operations.create_foreign_key(
        "fk_workflow_runtime_revisions_runtime",
        "workflow_runtime_revisions",
        "workflow_app_runtimes",
        ["workflow_runtime_id"],
        ["workflow_runtime_id"],
        ondelete="CASCADE",
    )
    operations.create_foreign_key(
        "fk_workflow_runtime_revisions_app_version",
        "workflow_runtime_revisions",
        "workflow_app_versions",
        ["workflow_app_version_id"],
        ["workflow_app_version_id"],
    )
    operations.create_table(
        _LIFECYCLE_TABLE,
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
    operations.create_index(
        _LIFECYCLE_STATE_INDEX,
        _LIFECYCLE_TABLE,
        ["state"],
    )
    operations.create_index(
        _LIFECYCLE_UPDATED_AT_INDEX,
        _LIFECYCLE_TABLE,
        ["updated_at"],
    )

    with operations.batch_alter_table("workflow_app_versions") as batch_op:
        batch_op.drop_constraint(
            "uq_workflow_app_version_content_deduplication",
            type_="unique",
        )
        batch_op.drop_column("content_deduplication_key")
    with operations.batch_alter_table("workflow_runs") as batch_op:
        batch_op.drop_column("worker_instance_id")

    return output.getvalue()


def _sqlite_settings(database_path: Path) -> BackendServiceSettings:
    """构造完全隔离的 SQLite 迁移测试配置。"""

    return BackendServiceSettings(
        database={
            "url": f"sqlite:///{database_path.as_posix()}",
            "echo": False,
        }
    )
