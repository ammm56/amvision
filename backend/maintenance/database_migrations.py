"""数据库 schema 迁移入口。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings, get_backend_service_settings


DATABASE_MIGRATION_COMMAND = "migrate-database"
_UNVERSIONED_SCHEMA_BASELINE_REVISION = "da5fa492b74d"


def migrate_database(
    *,
    backend_service_settings: BackendServiceSettings | None = None,
) -> dict[str, object]:
    """把配置中的数据库升级到当前 Alembic head。

    旧版本曾通过 ``create_all`` 建库而没有 ``alembic_version``。对这类数据库先
    补齐缺失表并标记初始基线，再执行后续幂等迁移，避免直接从头重复建表现有表。
    """

    settings = backend_service_settings or get_backend_service_settings()
    session_factory = SessionFactory(settings.to_database_settings())
    config = _build_alembic_config(settings)
    script = ScriptDirectory.from_config(config)
    target_heads = tuple(script.get_heads())
    try:
        with session_factory.engine.connect() as connection:
            current_heads = tuple(MigrationContext.configure(connection).get_current_heads())
            table_names = set(inspect(connection).get_table_names())

        if current_heads == target_heads:
            return {
                "command": DATABASE_MIGRATION_COMMAND,
                "changed": False,
                "previous_revisions": list(current_heads),
                "current_revisions": list(current_heads),
                "backup_file": None,
            }

        backup_file = _backup_sqlite_database(settings) if table_names else None
        if table_names and "alembic_version" not in table_names:
            initialize_database_schema(session_factory)
            command.stamp(config, _UNVERSIONED_SCHEMA_BASELINE_REVISION)
        command.upgrade(config, "head")

        with session_factory.engine.connect() as connection:
            migrated_heads = tuple(
                MigrationContext.configure(connection).get_current_heads()
            )
        if migrated_heads != target_heads:
            raise RuntimeError(
                "数据库迁移完成后 revision 不等于当前 head: "
                f"actual={migrated_heads}, expected={target_heads}"
            )
        return {
            "command": DATABASE_MIGRATION_COMMAND,
            "changed": True,
            "previous_revisions": list(current_heads),
            "current_revisions": list(migrated_heads),
            "backup_file": str(backup_file) if backup_file is not None else None,
        }
    finally:
        session_factory.engine.dispose()


def _build_alembic_config(settings: BackendServiceSettings) -> Config:
    """构造同时适用于源码目录和 release/app 目录的 Alembic 配置。"""

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str((backend_root / "alembic").resolve()))
    database_url = make_url(settings.database.url)
    if database_url.drivername.startswith("sqlite") and database_url.database not in {
        None,
        "",
        ":memory:",
    }:
        database_path = Path(str(database_url.database))
        if not database_path.is_absolute():
            database_path = (Path.cwd() / database_path).resolve()
        database_url = database_url.set(database=database_path.as_posix())
    config.set_main_option("sqlalchemy.url", database_url.render_as_string(hide_password=False))
    return config


def _backup_sqlite_database(settings: BackendServiceSettings) -> Path | None:
    """迁移前用 SQLite backup API 生成一致性备份，其他数据库返回 None。"""

    database_url = make_url(settings.database.url)
    if not database_url.drivername.startswith("sqlite"):
        return None
    database_value = database_url.database
    if not database_value or database_value == ":memory:":
        return None
    database_path = Path(database_value)
    if not database_path.is_absolute():
        database_path = (Path.cwd() / database_path).resolve()
    if not database_path.is_file():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = database_path.with_name(f"{database_path.name}.backup-{timestamp}")
    with sqlite3.connect(database_path) as source_connection:
        with sqlite3.connect(backup_path) as backup_connection:
            source_connection.backup(backup_connection)
    return backup_path
