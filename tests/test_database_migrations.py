"""数据库迁移 maintenance 测试。"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import (
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.engine.reflection import Inspector

from backend.maintenance.database_migrations import (
    _build_alembic_config,
    migrate_database,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings


_DATABASE_HEAD = "d8e4f6a1b3c7"


def test_migrate_database_adopts_unversioned_create_all_database(
    tmp_path: Path,
) -> None:
    """验证历史 create_all 数据库可安全纳入 Alembic 并升级到 head。"""

    database_path = tmp_path / "legacy.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )
    session_factory = SessionFactory(settings.to_database_settings())
    initialize_database_schema(session_factory)
    assert "alembic_version" not in inspect(session_factory.engine).get_table_names()
    session_factory.engine.dispose()

    first_result = migrate_database(backend_service_settings=settings)

    assert first_result["changed"] is True
    backup_file = first_result["backup_file"]
    assert isinstance(backup_file, str)
    assert Path(backup_file).is_file()
    verification_factory = SessionFactory(settings.to_database_settings())
    try:
        with verification_factory.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == _DATABASE_HEAD
        inspector = inspect(verification_factory.engine)
        assert "workflow_app_versions" in inspector.get_table_names()
        assert "workflow_runtime_revisions" in inspector.get_table_names()
        assert "queue_outbox_messages" in inspector.get_table_names()
        runtime_columns = {
            item["name"] for item in inspector.get_columns("workflow_app_runtimes")
        }
        assert {
            "active_revision_id",
            "desired_revision_id",
            "revision_generation",
            "worker_instance_id",
        } <= runtime_columns
        _assert_workflow_run_worker_instance_column(inspector)
        _assert_task_attempt_claim_uniqueness(inspector)
        _assert_conversion_publication_reservation(inspector)
        _assert_workflow_publish_deduplication(inspector)
        _assert_workflow_application_lifecycle(inspector)
    finally:
        verification_factory.engine.dispose()

    second_result = migrate_database(backend_service_settings=settings)
    assert second_result["changed"] is False
    assert second_result["backup_file"] is None


def test_migrate_database_initializes_empty_sqlite_database(tmp_path: Path) -> None:
    """验证全新数据库直接 upgrade head 并创建当前完整 schema。"""

    database_path = tmp_path / "new.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )

    result = migrate_database(backend_service_settings=settings)

    assert result["changed"] is True
    assert result["backup_file"] is None
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        inspector = inspect(session_factory.engine)
        table_names = set(inspector.get_table_names())
        assert "deployment_instances" in table_names
        assert "deployment_runtime_states" in table_names
        assert "workflow_app_versions" in table_names
        assert "workflow_runtime_revisions" in table_names
        assert "queue_outbox_messages" in table_names
        assert "alembic_version" in table_names
        _assert_worker_instance_column(inspector)
        _assert_workflow_run_worker_instance_column(inspector)
        _assert_training_task_supports_multiple_model_versions(inspector)
        _assert_task_attempt_claim_uniqueness(inspector)
        _assert_conversion_publication_reservation(inspector)
        _assert_workflow_publish_deduplication(inspector)
        _assert_workflow_application_lifecycle(inspector)
    finally:
        session_factory.engine.dispose()


def test_migrate_database_upgrades_preserved_task_idempotency_revision(
    tmp_path: Path,
) -> None:
    """验证已停留在 c4a2 的现场数据库可继续升级到 Workflow App 版本 head。"""

    database_path = tmp_path / "c4a2-existing.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )
    config = _build_alembic_config(settings)
    script = ScriptDirectory.from_config(config)
    assert script.get_revision("a1c7e9d4f2b6").down_revision == "e7a4c1d9b2f0"
    assert script.get_revision("b3f1e6a9c2d4").down_revision == "a1c7e9d4f2b6"
    assert script.get_revision("c4a2f7b8d3e5").down_revision == "b3f1e6a9c2d4"
    assert script.get_revision("a1b2c3d4e5f6").down_revision == "c4a2f7b8d3e5"
    assert script.get_revision("d5f8a1c3e7b9").down_revision == "a1b2c3d4e5f6"
    assert script.get_revision("e6c9b2d4f8a1").down_revision == "d5f8a1c3e7b9"
    assert script.get_revision("f7d1e3a5b9c2").down_revision == "e6c9b2d4f8a1"
    assert script.get_revision("f8a2c4e6b1d3").down_revision == "f7d1e3a5b9c2"
    assert script.get_revision("f9b3d5e7c2a4").down_revision == "f8a2c4e6b1d3"
    assert script.get_revision("fa4c6e8b1d25").down_revision == "f9b3d5e7c2a4"
    assert script.get_revision("b6e4f1a8c2d7").down_revision == "fa4c6e8b1d25"
    assert script.get_revision("c7a9e2d4f6b8").down_revision == "b6e4f1a8c2d7"
    assert script.get_revision(_DATABASE_HEAD).down_revision == "c7a9e2d4f6b8"
    assert script.get_current_head() == _DATABASE_HEAD

    command.upgrade(config, "c4a2f7b8d3e5")
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        _drop_columns(
            session_factory.engine,
            "workflow_app_runtimes",
            (
                "active_revision_id",
                "desired_revision_id",
                "revision_generation",
                "worker_instance_id",
            ),
        )
        _drop_columns(
            session_factory.engine,
            "workflow_runs",
            (
                "workflow_runtime_revision_id",
                "workflow_app_version_id",
                "runtime_generation",
                "snapshot_fingerprint",
                "worker_instance_id",
            ),
        )
        _replace_runtime_revision_table_without_foreign_keys(session_factory.engine)
        legacy_inspector = inspect(session_factory.engine)
        assert legacy_inspector.get_foreign_keys("workflow_runtime_revisions") == []
        assert "revision_generation" not in {
            item["name"]
            for item in legacy_inspector.get_columns("workflow_app_runtimes")
        }
        assert "worker_instance_id" not in {
            item["name"]
            for item in legacy_inspector.get_columns("workflow_app_runtimes")
        }
        assert "snapshot_fingerprint" not in {
            item["name"] for item in legacy_inspector.get_columns("workflow_runs")
        }
        assert "worker_instance_id" not in {
            item["name"] for item in legacy_inspector.get_columns("workflow_runs")
        }
        _insert_legacy_workflow_revision_records(session_factory.engine)
        with session_factory.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == "c4a2f7b8d3e5"
    finally:
        session_factory.engine.dispose()

    result = migrate_database(backend_service_settings=settings)
    assert result["previous_revisions"] == ["c4a2f7b8d3e5"]
    assert result["current_revisions"] == [_DATABASE_HEAD]
    assert isinstance(result["backup_file"], str)
    assert Path(result["backup_file"]).is_file()

    verification_factory = SessionFactory(settings.to_database_settings())
    try:
        inspector = inspect(verification_factory.engine)
        assert "workflow_app_versions" in inspector.get_table_names()
        assert "workflow_runtime_revisions" in inspector.get_table_names()
        _assert_workflow_runtime_revision_foreign_keys(inspector)
        _assert_worker_instance_column(inspector)
        _assert_workflow_run_worker_instance_column(inspector)
        _assert_training_task_supports_multiple_model_versions(inspector)
        _assert_workflow_publish_deduplication(inspector)
        _assert_workflow_application_lifecycle(inspector)
        assert {
            "active_revision_id",
            "desired_revision_id",
            "revision_generation",
        } <= {item["name"] for item in inspector.get_columns("workflow_app_runtimes")}
        assert {
            "workflow_runtime_revision_id",
            "workflow_app_version_id",
            "runtime_generation",
            "snapshot_fingerprint",
            "worker_instance_id",
        } <= {item["name"] for item in inspector.get_columns("workflow_runs")}
        assert {
            "ix_workflow_runtime_revisions_workflow_runtime_id",
            "ix_workflow_runtime_revisions_workflow_app_version_id",
            "ix_workflow_runtime_revisions_state",
            "ix_workflow_runtime_revisions_created_at",
        } <= {
            item["name"] for item in inspector.get_indexes("workflow_runtime_revisions")
        }
        with verification_factory.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            persisted_revision = connection.execute(
                text(
                    "SELECT workflow_runtime_id, workflow_app_version_id, generation "
                    "FROM workflow_runtime_revisions "
                    "WHERE workflow_runtime_revision_id = "
                    "'workflow-runtime-revision-legacy'"
                )
            ).one()
            worker_instance_id = connection.execute(
                text(
                    "SELECT worker_instance_id FROM workflow_app_runtimes "
                    "WHERE workflow_runtime_id = 'workflow-runtime-legacy'"
                )
            ).scalar_one()
        assert revision == _DATABASE_HEAD
        assert tuple(persisted_revision) == (
            "workflow-runtime-legacy",
            "workflow-app-version-legacy",
            1,
        )
        assert worker_instance_id is None
    finally:
        verification_factory.engine.dispose()

    command.check(config)

    command.downgrade(config, "c4a2f7b8d3e5")
    downgraded_factory = SessionFactory(settings.to_database_settings())
    try:
        assert "worker_instance_id" not in {
            item["name"]
            for item in inspect(downgraded_factory.engine).get_columns(
                "workflow_app_runtimes"
            )
        }
    finally:
        downgraded_factory.engine.dispose()
    command.upgrade(config, "head")
    roundtrip_factory = SessionFactory(settings.to_database_settings())
    try:
        roundtrip_inspector = inspect(roundtrip_factory.engine)
        _assert_workflow_runtime_revision_foreign_keys(roundtrip_inspector)
        _assert_worker_instance_column(roundtrip_inspector)
        _assert_workflow_run_worker_instance_column(roundtrip_inspector)
    finally:
        roundtrip_factory.engine.dispose()
    command.check(config)


def test_migrate_database_reconciles_already_applied_workflow_revision(
    tmp_path: Path,
) -> None:
    """验证已记录 a1b2 但缺外键的数据库可原地补齐且不丢数据。"""

    database_path = tmp_path / "a1b2-missing-foreign-keys.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )
    config = _build_alembic_config(settings)
    command.upgrade(config, "a1b2c3d4e5f6")
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        _drop_columns(
            session_factory.engine,
            "workflow_app_runtimes",
            ("worker_instance_id",),
        )
        _replace_runtime_revision_table_without_foreign_keys(session_factory.engine)
        _insert_legacy_workflow_revision_records(session_factory.engine)
        assert (
            inspect(session_factory.engine).get_foreign_keys(
                "workflow_runtime_revisions"
            )
            == []
        )
    finally:
        session_factory.engine.dispose()

    result = migrate_database(backend_service_settings=settings)

    assert result["previous_revisions"] == ["a1b2c3d4e5f6"]
    assert result["current_revisions"] == [_DATABASE_HEAD]
    assert isinstance(result["backup_file"], str)
    assert Path(result["backup_file"]).is_file()
    verification_factory = SessionFactory(settings.to_database_settings())
    try:
        inspector = inspect(verification_factory.engine)
        _assert_workflow_runtime_revision_foreign_keys(inspector)
        _assert_worker_instance_column(inspector)
        _assert_workflow_run_worker_instance_column(inspector)
        _assert_training_task_supports_multiple_model_versions(inspector)
        with verification_factory.engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM workflow_runtime_revisions "
                        "WHERE workflow_runtime_revision_id = "
                        "'workflow-runtime-revision-legacy'"
                    )
                ).scalar_one()
                == 1
            )
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        verification_factory.engine.dispose()
    command.check(config)


def test_publication_migration_rejects_active_legacy_conversion(
    tmp_path: Path,
) -> None:
    """验证旧协议 Conversion 未排空时 migration 在 DDL 前明确拒绝。"""

    database_path = tmp_path / "active-legacy-conversion.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )
    config = _build_alembic_config(settings)
    command.upgrade(config, "c7a9e2d4f6b8")
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        tasks = Table("tasks", MetaData(), autoload_with=session_factory.engine)
        with session_factory.engine.begin() as connection:
            connection.execute(
                tasks.insert().values(
                    task_id="conversion-active-before-upgrade",
                    task_kind="yolox-conversion",
                    display_name="active conversion",
                    project_id="project-1",
                    created_at="2026-08-24T00:00:00+00:00",
                    task_spec_json={},
                    metadata_json={},
                    state="running",
                    current_attempt_no=1,
                    progress_json={},
                    result_json={},
                )
            )
    finally:
        session_factory.engine.dispose()

    with pytest.raises(RuntimeError, match="活动 Conversion"):
        command.upgrade(config, "head")

    verification_factory = SessionFactory(settings.to_database_settings())
    try:
        with verification_factory.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == "c7a9e2d4f6b8"
    finally:
        verification_factory.engine.dispose()


def test_worker_epoch_migration_reconciles_training_task_uniqueness_drift(
    tmp_path: Path,
) -> None:
    """验证 f7 清理 e6 现场库中约束和独立 unique index 两种漂移。"""

    database_path = tmp_path / "e6-training-task-index-drift.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )
    config = _build_alembic_config(settings)
    command.upgrade(config, "e6c9b2d4f8a1")
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        # initial revision 使用当前 metadata 建表，需要显式还原成真实 e6 形态，
        # 确保本测试确实覆盖 f7 的 ADD COLUMN 路径。
        _drop_columns(
            session_factory.engine,
            "workflow_app_runtimes",
            ("worker_instance_id",),
        )
        _insert_model_version_for_migration_test(session_factory.engine)
        _add_training_task_uniqueness_drift(session_factory.engine)
        drift_inspector = inspect(session_factory.engine)
        assert "worker_instance_id" not in {
            item["name"]
            for item in drift_inspector.get_columns("workflow_app_runtimes")
        }
        assert ("training_task_id",) in {
            tuple(str(value) for value in item.get("column_names") or ())
            for item in drift_inspector.get_unique_constraints("model_versions")
        }
        assert any(
            bool(item.get("unique"))
            and tuple(str(value) for value in item.get("column_names") or ())
            == ("training_task_id",)
            for item in drift_inspector.get_indexes("model_versions")
        )
    finally:
        session_factory.engine.dispose()

    command.upgrade(config, "head")
    verification_factory = SessionFactory(settings.to_database_settings())
    try:
        inspector = inspect(verification_factory.engine)
        _assert_worker_instance_column(inspector)
        _assert_training_task_supports_multiple_model_versions(inspector)
        _insert_second_model_version_for_migration_test(verification_factory.engine)
        with verification_factory.engine.connect() as connection:
            version_ids = (
                connection.execute(
                    text(
                        "SELECT model_version_id FROM model_versions "
                        "WHERE training_task_id = 'training-task-migration' "
                        "ORDER BY model_version_id"
                    )
                )
                .scalars()
                .all()
            )
        assert version_ids == ["model-version-migration-1", "model-version-migration-2"]
    finally:
        verification_factory.engine.dispose()

    command.check(config)
    command.downgrade(config, "e6c9b2d4f8a1")
    downgraded_factory = SessionFactory(settings.to_database_settings())
    try:
        downgraded_inspector = inspect(downgraded_factory.engine)
        assert "worker_instance_id" not in {
            item["name"]
            for item in downgraded_inspector.get_columns("workflow_app_runtimes")
        }
        _assert_training_task_supports_multiple_model_versions(downgraded_inspector)
    finally:
        downgraded_factory.engine.dispose()


def test_workflow_run_worker_epoch_migration_preserves_historical_null(
    tmp_path: Path,
) -> None:
    """验证 f9 为历史 Run 保留 NULL，且 upgrade/downgrade 可往返。"""

    database_path = tmp_path / "f8-workflow-run-worker-epoch.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )
    config = _build_alembic_config(settings)
    command.upgrade(config, "f8a2c4e6b1d3")
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        # initial revision 使用当前 metadata 建表，显式还原真实 f8 形态。
        _drop_columns(
            session_factory.engine,
            "workflow_runs",
            ("worker_instance_id",),
        )
        workflow_runs = Table(
            "workflow_runs",
            MetaData(),
            autoload_with=session_factory.engine,
        )
        with session_factory.engine.begin() as connection:
            connection.execute(
                workflow_runs.insert().values(
                    workflow_run_id="workflow-run-before-f9",
                    workflow_runtime_id="workflow-runtime-before-f9",
                    project_id="project-1",
                    application_id="application-1",
                    workflow_runtime_revision_id=None,
                    workflow_app_version_id=None,
                    runtime_generation=None,
                    snapshot_fingerprint=None,
                    state="succeeded",
                    created_at="2026-08-19T00:00:00Z",
                    started_at=None,
                    finished_at="2026-08-19T00:00:01Z",
                    created_by=None,
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
    finally:
        session_factory.engine.dispose()

    command.upgrade(config, "head")
    verification_factory = SessionFactory(settings.to_database_settings())
    try:
        inspector = inspect(verification_factory.engine)
        _assert_workflow_run_worker_instance_column(inspector)
        with verification_factory.engine.connect() as connection:
            worker_instance_id = connection.execute(
                text(
                    "SELECT worker_instance_id FROM workflow_runs "
                    "WHERE workflow_run_id = 'workflow-run-before-f9'"
                )
            ).scalar_one()
        assert worker_instance_id is None
    finally:
        verification_factory.engine.dispose()

    command.check(config)
    command.downgrade(config, "f8a2c4e6b1d3")
    downgraded_factory = SessionFactory(settings.to_database_settings())
    try:
        assert "worker_instance_id" not in {
            str(item["name"])
            for item in inspect(downgraded_factory.engine).get_columns("workflow_runs")
        }
    finally:
        downgraded_factory.engine.dispose()

    command.upgrade(config, "head")
    roundtrip_factory = SessionFactory(settings.to_database_settings())
    try:
        _assert_workflow_run_worker_instance_column(inspect(roundtrip_factory.engine))
    finally:
        roundtrip_factory.engine.dispose()


def _add_training_task_uniqueness_drift(engine: Engine) -> None:
    """模拟 e6 后仍同时残留唯一约束和独立 unique index 的现场库。"""

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table("model_versions") as batch_op:
            batch_op.create_unique_constraint(
                "uq_model_versions_training_task_drift",
                ["training_task_id"],
            )

    model_versions = Table(
        "model_versions",
        MetaData(),
        autoload_with=engine,
    )
    Index(
        "ux_model_versions_training_task_drift",
        model_versions.c.training_task_id,
        unique=True,
    ).create(engine)


def _insert_model_version_for_migration_test(engine: Engine) -> None:
    """写入一组模型和版本数据，用于验证 f7 不丢失业务记录。"""

    metadata = MetaData()
    models = Table("models", metadata, autoload_with=engine)
    model_versions = Table("model_versions", metadata, autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            models.insert().values(
                model_id="model-migration",
                project_id="project-migration",
                owner_key="project-migration",
                scope_kind="project",
                model_name="migration-model",
                model_type="yolo11",
                task_type="detection",
                model_scale="n",
                labels_file_id=None,
                metadata_json={},
            )
        )
        connection.execute(
            model_versions.insert().values(
                model_version_id="model-version-migration-1",
                model_id="model-migration",
                source_kind="training-output",
                dataset_version_id=None,
                training_task_id="training-task-migration",
                parent_version_id=None,
                file_ids_json=[],
                metadata_json={},
            )
        )


def _insert_second_model_version_for_migration_test(engine: Engine) -> None:
    """用相同 training_task_id 写入第二个版本，验证唯一性已解除。"""

    model_versions = Table(
        "model_versions",
        MetaData(),
        autoload_with=engine,
    )
    with engine.begin() as connection:
        connection.execute(
            model_versions.insert().values(
                model_version_id="model-version-migration-2",
                model_id="model-migration",
                source_kind="training-output",
                dataset_version_id=None,
                training_task_id="training-task-migration",
                parent_version_id=None,
                file_ids_json=[],
                metadata_json={},
            )
        )


def _replace_runtime_revision_table_without_foreign_keys(engine: Engine) -> None:
    """重建带数据约束和索引、但缺父记录外键的历史 revision 表。"""

    existing_table = Table(
        "workflow_runtime_revisions",
        MetaData(),
        autoload_with=engine,
    )
    existing_table.drop(engine)
    Table(
        "workflow_runtime_revisions",
        MetaData(),
        Column("workflow_runtime_revision_id", String(128), primary_key=True),
        Column("workflow_runtime_id", String(128), nullable=False),
        Column("generation", Integer, nullable=False),
        Column("workflow_app_version_id", String(128), nullable=False),
        Column("execution_policy_snapshot_object_key", String(1024), nullable=True),
        Column("expected_snapshot_fingerprint", String(256), nullable=False),
        Column("state", String(32), nullable=False),
        Column("created_at", String(64), nullable=False),
        Column("activated_at", String(64), nullable=True),
        Column("failed_at", String(64), nullable=True),
        Column("error", String(2048), nullable=True),
        Column("created_by", String(128), nullable=True),
        UniqueConstraint(
            "workflow_runtime_id",
            "generation",
            name="uq_workflow_runtime_revision_generation",
        ),
        Index(
            "ix_workflow_runtime_revisions_workflow_runtime_id",
            "workflow_runtime_id",
        ),
        Index(
            "ix_workflow_runtime_revisions_workflow_app_version_id",
            "workflow_app_version_id",
        ),
        Index("ix_workflow_runtime_revisions_state", "state"),
        Index("ix_workflow_runtime_revisions_created_at", "created_at"),
    ).create(engine)


def _drop_columns(
    engine: Engine,
    table_name: str,
    column_names: tuple[str, ...],
) -> None:
    """把当前 metadata 提前建出的新字段还原为历史 c4 形态。"""

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table(table_name) as batch_op:
            for column_name in column_names:
                batch_op.drop_column(column_name)


def _insert_legacy_workflow_revision_records(engine: Engine) -> None:
    """写入一组引用完整的旧 App Version、Runtime 和 revision。"""

    metadata = MetaData()
    app_versions = Table("workflow_app_versions", metadata, autoload_with=engine)
    runtimes = Table("workflow_app_runtimes", metadata, autoload_with=engine)
    revisions = Table("workflow_runtime_revisions", metadata, autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            app_versions.insert().values(
                workflow_app_version_id="workflow-app-version-legacy",
                project_id="project-legacy",
                application_id="workflow-app-legacy",
                version_number=1,
                display_version="1",
                release_notes="",
                application_snapshot_object_key="workflow/apps/legacy/application.json",
                template_snapshot_object_key="workflow/apps/legacy/template.json",
                contract_snapshot_object_key="workflow/apps/legacy/contract.json",
                dependency_manifest_object_key="workflow/apps/legacy/dependencies.json",
                content_fingerprint="legacy-content-fingerprint",
                contract_fingerprint="legacy-contract-fingerprint",
                state="ready",
                created_at="2026-08-19T00:00:00Z",
                created_by="migration-test",
                completed_at="2026-08-19T00:00:00Z",
                error=None,
            )
        )
        runtime_values: dict[str, object] = {
            "workflow_runtime_id": "workflow-runtime-legacy",
            "project_id": "project-legacy",
            "application_id": "workflow-app-legacy",
            "display_name": "legacy runtime",
            "application_snapshot_object_key": (
                "workflow/apps/legacy/application.json"
            ),
            "template_snapshot_object_key": "workflow/apps/legacy/template.json",
            "execution_policy_snapshot_object_key": None,
            "desired_state": "stopped",
            "observed_state": "stopped",
            "request_timeout_seconds": 60,
            "heartbeat_interval_seconds": 5,
            "heartbeat_timeout_seconds": 15,
            "created_at": "2026-08-19T00:00:00Z",
            "updated_at": "2026-08-19T00:00:00Z",
            "created_by": "migration-test",
            "last_started_at": None,
            "last_stopped_at": None,
            "heartbeat_at": None,
            "worker_process_id": None,
            "loaded_snapshot_fingerprint": None,
            "last_error": None,
            "health_summary_json": {},
            "metadata_json": {},
        }
        if "revision_generation" in runtimes.c:
            runtime_values.update(
                {
                    "active_revision_id": "workflow-runtime-revision-legacy",
                    "desired_revision_id": "workflow-runtime-revision-legacy",
                    "revision_generation": 1,
                }
            )
        connection.execute(runtimes.insert().values(**runtime_values))
        connection.execute(
            revisions.insert().values(
                workflow_runtime_revision_id="workflow-runtime-revision-legacy",
                workflow_runtime_id="workflow-runtime-legacy",
                generation=1,
                workflow_app_version_id="workflow-app-version-legacy",
                execution_policy_snapshot_object_key=None,
                expected_snapshot_fingerprint="legacy-content-fingerprint",
                state="active",
                created_at="2026-08-19T00:00:00Z",
                activated_at="2026-08-19T00:00:00Z",
                failed_at=None,
                error=None,
                created_by="migration-test",
            )
        )


def _assert_workflow_runtime_revision_foreign_keys(inspector: Inspector) -> None:
    """断言 Runtime revision 的两条父记录外键完整。"""

    foreign_keys = inspector.get_foreign_keys("workflow_runtime_revisions")
    signatures = {
        (
            tuple(item["constrained_columns"]),
            item["referred_table"],
            tuple(item["referred_columns"]),
            (item.get("options") or {}).get("ondelete"),
        )
        for item in foreign_keys
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


def _assert_worker_instance_column(inspector: Inspector) -> None:
    """断言 Runtime worker epoch 字段的类型和空值语义正确。"""

    columns = {
        str(item["name"]): item
        for item in inspector.get_columns("workflow_app_runtimes")
    }
    worker_column = columns["worker_instance_id"]
    assert worker_column["nullable"] is True
    assert worker_column["type"].length == 128


def _assert_workflow_run_worker_instance_column(inspector: Inspector) -> None:
    """断言 WorkflowRun worker epoch 来源字段的类型和历史空值语义。"""

    columns = {
        str(item["name"]): item for item in inspector.get_columns("workflow_runs")
    }
    worker_column = columns["worker_instance_id"]
    assert worker_column["nullable"] is True
    assert worker_column["type"].length == 128


def _assert_training_task_supports_multiple_model_versions(
    inspector: Inspector,
) -> None:
    """断言训练任务字段只有查询索引，不再承担一对一唯一约束。"""

    unique_column_sets = {
        tuple(str(value) for value in item.get("column_names") or ())
        for item in inspector.get_unique_constraints("model_versions")
    }
    assert ("training_task_id",) not in unique_column_sets
    matching_indexes = {
        str(item["name"]): item
        for item in inspector.get_indexes("model_versions")
        if tuple(str(value) for value in item.get("column_names") or ())
        == ("training_task_id",)
    }
    assert matching_indexes
    assert not any(bool(item.get("unique")) for item in matching_indexes.values())
    canonical_index = matching_indexes["ix_model_versions_training_task_id"]
    assert bool(canonical_index.get("unique")) is False


def _assert_task_attempt_claim_uniqueness(inspector: Inspector) -> None:
    """断言同一 Task 的 attempt_no 只能被一个 worker 原子领取。"""

    unique_column_sets = {
        tuple(str(value) for value in item.get("column_names") or ())
        for item in inspector.get_unique_constraints("task_attempts")
    }
    assert ("task_id", "attempt_no") in unique_column_sets


def _assert_conversion_publication_reservation(inspector: Inspector) -> None:
    """断言 Conversion publication 内部字段、约束和恢复索引完整。"""

    columns = {str(item["name"]): item for item in inspector.get_columns("tasks")}
    for column_name in (
        "publication_state",
        "publication_token",
        "publication_attempt_no",
        "publication_updated_at",
    ):
        assert columns[column_name]["nullable"] is True
    assert columns["publication_state"]["type"].length == 32
    assert columns["publication_token"]["type"].length == 64
    assert columns["publication_updated_at"]["type"].length == 64
    indexes = {
        str(item["name"]): tuple(item.get("column_names") or ())
        for item in inspector.get_indexes("tasks")
    }
    assert indexes["ix_tasks_publication_recovery"] == (
        "publication_state",
        "publication_updated_at",
    )
    constraints = {
        str(item["name"])
        for item in inspector.get_check_constraints("tasks")
        if item.get("name")
    }
    assert "ck_tasks_publication_fields_complete" in constraints


def _assert_workflow_publish_deduplication(inspector: Inspector) -> None:
    """断言默认内容发布占位字段和唯一约束完整。"""

    columns = {
        str(item["name"]): item
        for item in inspector.get_columns("workflow_app_versions")
    }
    deduplication_column = columns["content_deduplication_key"]
    assert deduplication_column["nullable"] is True
    assert deduplication_column["type"].length == 256
    unique_column_sets = {
        tuple(str(value) for value in item.get("column_names") or ())
        for item in inspector.get_unique_constraints("workflow_app_versions")
    }
    assert (
        "project_id",
        "application_id",
        "content_deduplication_key",
    ) in unique_column_sets


def _assert_workflow_application_lifecycle(inspector: Inspector) -> None:
    """断言 Application 复合主键状态门可在三类数据库统一迁移。"""

    table_name = "workflow_application_lifecycles"
    assert table_name in inspector.get_table_names()
    columns = {str(item["name"]): item for item in inspector.get_columns(table_name)}
    assert set(columns) == {
        "project_id",
        "application_id",
        "state",
        "generation",
        "operation_id",
        "updated_at",
        "deleted",
    }
    assert columns["project_id"]["type"].length == 128
    assert columns["application_id"]["type"].length == 128
    assert columns["operation_id"]["nullable"] is True
    assert columns["deleted"]["nullable"] is False
    primary_key = inspector.get_pk_constraint(table_name)
    assert tuple(primary_key["constrained_columns"]) == (
        "project_id",
        "application_id",
    )
    indexes = {str(item["name"]) for item in inspector.get_indexes(table_name)}
    assert {
        "ix_workflow_application_lifecycles_state",
        "ix_workflow_application_lifecycles_updated_at",
    } <= indexes
