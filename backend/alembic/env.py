"""Alembic 环境配置。"""

from __future__ import annotations

from importlib import import_module
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url
from alembic import context

# 导入项目 ORM Base 和所有实体模型
from backend.service.infrastructure.persistence.base import Base

# 加载所有 ORM 实体模块，确保 Base.metadata 包含完整表结构。
_ORM_MODULES = (
    "backend.service.infrastructure.persistence.model_orm",
    "backend.service.infrastructure.persistence.model_file_orm",
    "backend.service.infrastructure.persistence.dataset_orm",
    "backend.service.infrastructure.persistence.dataset_import_orm",
    "backend.service.infrastructure.persistence.dataset_export_orm",
    "backend.service.infrastructure.persistence.task_orm",
    "backend.service.infrastructure.persistence.deployment_orm",
    "backend.service.infrastructure.persistence.workflow_runtime_orm",
    "backend.service.infrastructure.persistence.workflow_trigger_source_orm",
    "backend.service.infrastructure.persistence.local_auth_orm",
)

for module_name in _ORM_MODULES:
    import_module(module_name)

# Alembic Config 对象
config = context.config

# 配置日志（显式指定 UTF-8 编码，避免 Windows 中文系统下 locale 回退为 GBK）
if config.config_file_name is not None:
    fileConfig(config.config_file_name, encoding="utf-8")

# 目标 metadata
target_metadata = Base.metadata


def _resolve_sqlite_url_from_config_dir(url: str | None) -> str | None:
    """将 alembic.ini 中的相对 SQLite 路径固定按配置文件目录解析。"""
    if not url:
        return url
    parsed_url = make_url(url)
    if not parsed_url.drivername.startswith("sqlite"):
        return url
    database = parsed_url.database
    if not database or database == ":memory:":
        return url
    database_path = Path(database)
    if database_path.is_absolute() or config.config_file_name is None:
        return url
    config_dir = Path(config.config_file_name).resolve().parent
    resolved_database = (config_dir / database_path).resolve()
    return str(parsed_url.set(database=resolved_database.as_posix()))


def _apply_resolved_database_url() -> None:
    """修正数据库 URL，避免从不同工作目录执行 Alembic 时路径跑偏。"""
    raw_url = config.get_main_option("sqlalchemy.url")
    resolved_url = _resolve_sqlite_url_from_config_dir(raw_url)
    if resolved_url and resolved_url != raw_url:
        config.set_main_option("sqlalchemy.url", resolved_url)


_apply_resolved_database_url()


def run_migrations_offline() -> None:
    """以 'offline' 模式运行迁移。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """以 'online' 模式运行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
