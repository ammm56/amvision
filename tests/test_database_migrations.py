"""数据库迁移 maintenance 测试。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from backend.maintenance.database_migrations import migrate_database
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings


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
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "e7a4c1d9b2f0"
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
        table_names = set(inspect(session_factory.engine).get_table_names())
        assert "deployment_instances" in table_names
        assert "deployment_runtime_states" in table_names
        assert "alembic_version" in table_names
    finally:
        session_factory.engine.dispose()
