"""数据库 URL 的百分号编码必须经过 Alembic 配置后保持原值。"""

from pathlib import Path
import logging

import pytest

from sqlalchemy.engine import URL, make_url

from backend.maintenance.database_migrations import _build_alembic_config, migrate_database
from backend.service.settings import BackendServiceSettings


def test_migration_preserves_encoded_password() -> None:
    """MySQL/PostgreSQL 凭据中的编码字符不能被 ConfigParser 当作插值。"""
    url = URL.create("postgresql", username="example", password="p%@ss/word", host="localhost", database="example")
    settings = BackendServiceSettings(database={"url": url.render_as_string(hide_password=False)})
    config = _build_alembic_config(settings)
    assert make_url(config.get_main_option("sqlalchemy.url")) == url


def test_migration_creates_only_requested_sqlite_path(tmp_path: Path) -> None:
    """包含百分号、空格和中文的路径执行真实迁移，不能生成编码后的错误目录。"""
    path = tmp_path / "工业 100%" / "amvision.db"
    url = URL.create("sqlite", database=path.as_posix())
    settings = BackendServiceSettings(database={"url": url.render_as_string(hide_password=False)})
    config = _build_alembic_config(settings)
    assert make_url(config.get_main_option("sqlalchemy.url")).database == path.as_posix()
    result = migrate_database(backend_service_settings=settings)
    assert result["changed"] is True
    assert path.is_file()
    assert migrate_database(backend_service_settings=settings)["changed"] is False


@pytest.mark.parametrize("fail_after_upgrade", [False, True])
def test_embedded_migration_preserves_host_logging(tmp_path, monkeypatch, caplog, fail_after_upgrade):
    """真实迁移成功或失败都不能修改宿主 logger 或关闭宿主 handler。"""
    from backend.maintenance import database_migrations
    logger = logging.getLogger("backend.service.application.workflows.execution.events")
    root = logging.getLogger()
    caplog.set_level(logging.ERROR)

    def snapshot(current):
        """保留全局日志配置的可观测状态。"""
        return current.level, current.disabled, current.propagate, tuple(current.handlers), tuple(
            (handler.level, handler.formatter, handler._closed) for handler in current.handlers
        )

    before = snapshot(root), snapshot(logger)
    original_upgrade = database_migrations.command.upgrade

    def upgrade_then_fail(*args, **kwargs):
        """在 Alembic 环境确实执行后模拟迁移调用失败。"""
        original_upgrade(*args, **kwargs)
        raise RuntimeError("injected migration failure")

    if fail_after_upgrade:
        monkeypatch.setattr(database_migrations.command, "upgrade", upgrade_then_fail)
    url = URL.create("sqlite", database=(tmp_path / "logging.db").as_posix())
    settings = BackendServiceSettings(database={"url": url.render_as_string(hide_password=False)})
    if fail_after_upgrade:
        with pytest.raises(RuntimeError, match="injected"):
            migrate_database(backend_service_settings=settings)
    else:
        migrate_database(backend_service_settings=settings)
    assert (snapshot(root), snapshot(logger)) == before
    logger.error("logging-after-migration")
    assert any(record.message == "logging-after-migration" for record in caplog.records)
