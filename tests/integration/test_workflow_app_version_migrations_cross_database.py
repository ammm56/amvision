"""可选 MySQL/PostgreSQL Workflow App 版本迁移集成门禁。

本文件不属于默认 pytest 递归范围。仅对显式提供的专用临时数据库执行破坏性
upgrade/downgrade；普通开发和本地 SQLite 运行不依赖外部数据库或 Docker。
"""

from __future__ import annotations

import os

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy import MetaData, Table, inspect, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError

from backend.maintenance.database_migrations import _build_alembic_config
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings


_ALLOW_DESTRUCTIVE_ENV = "AMVISION_CROSS_DB_MIGRATION_ALLOW_DESTRUCTIVE"
_TARGET_ENVIRONMENTS = (
    ("mysql", "AMVISION_TEST_MYSQL_DATABASE_URL"),
    ("postgresql", "AMVISION_TEST_POSTGRESQL_DATABASE_URL"),
)
_DATABASE_PREFIX = "amvision_migration_test_"
_F7_REVISION_PARENT = "e6c9b2d4f8a1"
_HEAD_REVISION = "fa4c6e8b1d25"


def _configured_targets() -> list[pytest.ParameterSet]:
    """读取显式集成测试 URL，不提供时生成一条可见的 skip。"""

    targets: list[pytest.ParameterSet] = []
    for expected_dialect, environment_name in _TARGET_ENVIRONMENTS:
        database_url = os.environ.get(environment_name, "").strip()
        if database_url:
            targets.append(
                pytest.param(expected_dialect, database_url, id=expected_dialect)
            )
    if targets:
        return targets
    return [
        pytest.param(
            "unconfigured",
            "",
            marks=pytest.mark.skip(reason="未配置可选 MySQL/PostgreSQL 迁移测试数据库"),
            id="unconfigured",
        )
    ]


@pytest.mark.parametrize(("expected_dialect", "database_url"), _configured_targets())
def test_workflow_app_version_migrations_on_server_database(
    expected_dialect: str,
    database_url: str,
) -> None:
    """在专用空数据库执行 e6 -> head -> e6 -> head 的真实往返。"""

    _require_safe_dedicated_database(
        expected_dialect=expected_dialect,
        database_url=database_url,
    )
    settings = BackendServiceSettings(database={"url": database_url, "echo": False})
    config = _build_alembic_config(settings)
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        assert inspect(session_factory.engine).get_table_names() == []
    finally:
        session_factory.engine.dispose()

    database_initialized = False
    try:
        command.upgrade(config, _F7_REVISION_PARENT)
        database_initialized = True
        _restore_true_e6_shape_and_seed_history(settings)

        command.upgrade(config, "head")
        command.check(config)
        _assert_head_schema_and_data(settings)

        command.downgrade(config, _F7_REVISION_PARENT)
        _assert_e6_shape(settings)

        command.upgrade(config, "head")
        command.check(config)
        _assert_head_schema_and_data(settings)
    finally:
        if database_initialized:
            command.downgrade(config, "base")


def _require_safe_dedicated_database(
    *,
    expected_dialect: str,
    database_url: str,
) -> None:
    """拒绝对非显式专用数据库执行破坏性迁移测试。"""

    if os.environ.get(_ALLOW_DESTRUCTIVE_ENV) != "1":
        pytest.fail(f"必须显式设置 {_ALLOW_DESTRUCTIVE_ENV}=1 才能运行跨数据库迁移门禁")
    parsed = make_url(database_url)
    actual_dialect = parsed.get_backend_name()
    if actual_dialect != expected_dialect:
        pytest.fail(
            f"测试 URL 方言不匹配: actual={actual_dialect!r}, "
            f"expected={expected_dialect!r}"
        )
    database_name = str(parsed.database or "")
    if not database_name.startswith(_DATABASE_PREFIX):
        pytest.fail(
            "跨数据库迁移门禁只允许使用名称以 "
            f"{_DATABASE_PREFIX!r} 开头的专用临时数据库"
        )


def _restore_true_e6_shape_and_seed_history(
    settings: BackendServiceSettings,
) -> None:
    """移除 initial metadata 提前创建的 f7-fa schema，并写入历史记录。"""

    session_factory = SessionFactory(settings.to_database_settings())
    try:
        engine = session_factory.engine
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            _drop_unique_constraint_by_columns(
                connection,
                operations,
                table_name="workflow_app_versions",
                column_names=(
                    "project_id",
                    "application_id",
                    "content_deduplication_key",
                ),
            )
            with operations.batch_alter_table("workflow_app_versions") as batch_op:
                batch_op.drop_column("content_deduplication_key")
            with operations.batch_alter_table("workflow_app_runtimes") as batch_op:
                batch_op.drop_column("worker_instance_id")
            with operations.batch_alter_table("workflow_runs") as batch_op:
                batch_op.drop_column("worker_instance_id")
            lifecycle = Table(
                "workflow_application_lifecycles",
                MetaData(),
                autoload_with=connection,
            )
            lifecycle.drop(connection)

        _seed_versions_before_deduplication(engine)
        _seed_historical_run_before_worker_epoch(engine)
    finally:
        session_factory.engine.dispose()


def _drop_unique_constraint_by_columns(
    connection: Connection,
    operations: Operations,
    *,
    table_name: str,
    column_names: tuple[str, ...],
) -> None:
    """按字段签名删除 initial metadata 创建的命名唯一约束。"""

    matching = [
        item
        for item in inspect(connection).get_unique_constraints(table_name)
        if tuple(str(value) for value in item.get("column_names") or ()) == column_names
    ]
    assert len(matching) == 1
    constraint_name = matching[0].get("name")
    assert constraint_name
    with operations.batch_alter_table(table_name) as batch_op:
        batch_op.drop_constraint(str(constraint_name), type_="unique")


def _seed_versions_before_deduplication(engine: Engine) -> None:
    """写入同内容的两个历史版本，验证 f8 选择唯一规范占位。"""

    versions = Table("workflow_app_versions", MetaData(), autoload_with=engine)
    common = {
        "project_id": "project-cross-db",
        "application_id": "application-cross-db",
        "display_version": "1",
        "release_notes": "",
        "application_snapshot_object_key": "workflow/application.json",
        "template_snapshot_object_key": "workflow/template.json",
        "contract_snapshot_object_key": "workflow/contract.json",
        "dependency_manifest_object_key": "workflow/dependencies.json",
        "content_fingerprint": "content-fingerprint-cross-db",
        "contract_fingerprint": "contract-fingerprint-cross-db",
        "state": "published",
        "created_at": "2026-08-19T00:00:00Z",
        "created_by": "migration-test",
        "completed_at": "2026-08-19T00:00:01Z",
        "error": None,
    }
    with engine.begin() as connection:
        connection.execute(
            versions.insert(),
            (
                {
                    **common,
                    "workflow_app_version_id": "workflow-app-version-cross-db-1",
                    "version_number": 1,
                },
                {
                    **common,
                    "workflow_app_version_id": "workflow-app-version-cross-db-2",
                    "version_number": 2,
                },
            ),
        )


def _seed_historical_run_before_worker_epoch(engine: Engine) -> None:
    """写入 f9 之前的 Run，验证迁移不会猜测 worker epoch。"""

    workflow_runs = Table("workflow_runs", MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            workflow_runs.insert().values(
                workflow_run_id="workflow-run-cross-db",
                workflow_runtime_id="workflow-runtime-cross-db",
                project_id="project-cross-db",
                application_id="application-cross-db",
                workflow_runtime_revision_id=None,
                workflow_app_version_id=None,
                runtime_generation=None,
                snapshot_fingerprint=None,
                state="succeeded",
                created_at="2026-08-19T00:00:00Z",
                started_at=None,
                finished_at="2026-08-19T00:00:01Z",
                created_by="migration-test",
                requested_timeout_seconds=60,
                assigned_process_id=None,
                input_payload_json={},
                outputs_json={},
                template_outputs_json={},
                node_records_json=[],
                error_message=None,
                metadata_json={},
            )
        )


def _assert_head_schema_and_data(settings: BackendServiceSettings) -> None:
    """核对 head 的 FK、命名唯一约束、NULL epoch、dedup 和 lifecycle。"""

    session_factory = SessionFactory(settings.to_database_settings())
    try:
        inspector = inspect(session_factory.engine)
        with session_factory.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            worker_instance_id = connection.execute(
                text(
                    "SELECT worker_instance_id FROM workflow_runs "
                    "WHERE workflow_run_id = 'workflow-run-cross-db'"
                )
            ).scalar_one()
            deduplication_rows = connection.execute(
                text(
                    "SELECT workflow_app_version_id, content_deduplication_key "
                    "FROM workflow_app_versions "
                    "WHERE workflow_app_version_id IN "
                    "('workflow-app-version-cross-db-1', "
                    "'workflow-app-version-cross-db-2') "
                    "ORDER BY version_number"
                )
            ).all()
        assert revision == _HEAD_REVISION
        assert worker_instance_id is None
        assert deduplication_rows == [
            ("workflow-app-version-cross-db-1", None),
            (
                "workflow-app-version-cross-db-2",
                "content-fingerprint-cross-db",
            ),
        ]

        runtime_worker = {
            str(item["name"]): item
            for item in inspector.get_columns("workflow_app_runtimes")
        }["worker_instance_id"]
        run_worker = {
            str(item["name"]): item for item in inspector.get_columns("workflow_runs")
        }["worker_instance_id"]
        assert runtime_worker["nullable"] is True
        assert run_worker["nullable"] is True

        unique_constraints = {
            str(item.get("name")): tuple(item.get("column_names") or ())
            for item in inspector.get_unique_constraints("workflow_app_versions")
        }
        assert unique_constraints["uq_workflow_app_version_content_deduplication"] == (
            "project_id",
            "application_id",
            "content_deduplication_key",
        )
        _assert_runtime_revision_foreign_keys(inspector)

        assert "workflow_application_lifecycles" in inspector.get_table_names()
        assert tuple(
            inspector.get_pk_constraint("workflow_application_lifecycles")[
                "constrained_columns"
            ]
        ) == ("project_id", "application_id")
        assert {
            "ix_workflow_application_lifecycles_state",
            "ix_workflow_application_lifecycles_updated_at",
        } <= {
            str(item["name"])
            for item in inspector.get_indexes("workflow_application_lifecycles")
        }

        _assert_nullable_deduplication_allows_multiple_rows(session_factory.engine)
    finally:
        session_factory.engine.dispose()


def _assert_nullable_deduplication_allows_multiple_rows(engine: Engine) -> None:
    """验证 MySQL/PostgreSQL 对 NULL 去重占位均允许多条记录。"""

    versions = Table("workflow_app_versions", MetaData(), autoload_with=engine)
    source = {
        "project_id": "project-cross-db",
        "application_id": "application-cross-db",
        "display_version": "3",
        "release_notes": "",
        "application_snapshot_object_key": "workflow/application.json",
        "template_snapshot_object_key": "workflow/template.json",
        "contract_snapshot_object_key": "workflow/contract.json",
        "dependency_manifest_object_key": "workflow/dependencies.json",
        "content_fingerprint": "content-fingerprint-null-cross-db",
        "content_deduplication_key": None,
        "contract_fingerprint": "contract-fingerprint-cross-db",
        "state": "published",
        "created_at": "2026-08-19T00:00:02Z",
        "created_by": "migration-test",
        "completed_at": "2026-08-19T00:00:03Z",
        "error": None,
    }
    with engine.begin() as connection:
        existing = connection.execute(
            sa.select(sa.func.count())
            .select_from(versions)
            .where(
                versions.c.workflow_app_version_id
                == "workflow-app-version-cross-db-null"
            )
        ).scalar_one()
        if not existing:
            connection.execute(
                versions.insert().values(
                    **source,
                    workflow_app_version_id=("workflow-app-version-cross-db-null"),
                    version_number=3,
                )
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                versions.insert().values(
                    **{
                        **source,
                        "content_deduplication_key": ("content-fingerprint-cross-db"),
                    },
                    workflow_app_version_id=("workflow-app-version-cross-db-duplicate"),
                    version_number=4,
                )
            )


def _assert_runtime_revision_foreign_keys(inspector: Inspector) -> None:
    """核对两条 Runtime revision 父记录外键。"""

    signatures = {
        (
            tuple(item.get("constrained_columns") or ()),
            str(item.get("referred_table")),
            tuple(item.get("referred_columns") or ()),
            _normalize_foreign_key_action((item.get("options") or {}).get("ondelete")),
        )
        for item in inspector.get_foreign_keys("workflow_runtime_revisions")
    }
    assert (
        ("workflow_runtime_id",),
        "workflow_app_runtimes",
        ("workflow_runtime_id",),
        "CASCADE",
    ) in signatures
    assert (
        ("workflow_app_version_id",),
        "workflow_app_versions",
        ("workflow_app_version_id",),
        None,
    ) in signatures


def _normalize_foreign_key_action(value: object) -> str | None:
    """统一服务器可能返回的默认 NO ACTION。"""

    normalized = str(value or "").strip().upper()
    return None if normalized in {"", "NO ACTION"} else normalized


def _assert_e6_shape(settings: BackendServiceSettings) -> None:
    """核对 downgrade 后 f7-fa schema 已移除且业务记录保留。"""

    session_factory = SessionFactory(settings.to_database_settings())
    try:
        inspector = inspect(session_factory.engine)
        assert "worker_instance_id" not in {
            str(item["name"]) for item in inspector.get_columns("workflow_app_runtimes")
        }
        assert "worker_instance_id" not in {
            str(item["name"]) for item in inspector.get_columns("workflow_runs")
        }
        assert "content_deduplication_key" not in {
            str(item["name"]) for item in inspector.get_columns("workflow_app_versions")
        }
        assert "workflow_application_lifecycles" not in inspector.get_table_names()
        with session_factory.engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM workflow_runs "
                        "WHERE workflow_run_id = 'workflow-run-cross-db'"
                    )
                ).scalar_one()
                == 1
            )
    finally:
        session_factory.engine.dispose()
