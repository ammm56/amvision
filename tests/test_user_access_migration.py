"""页面字段迁移与并发管理员保护。"""

import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic import command
from alembic.config import Config
from pathlib import Path

from backend.service.application.auth.local_auth_service import (
    LocalAuthService, LocalAuthUserUpdateRequest,
)
from backend.service.application.errors import ServiceError
from backend.service.settings import BackendServiceSettings
from tests.test_local_auth_api import _create_local_auth_test_client


def test_empty_sqlite_database_upgrades_through_complete_revision_chain(tmp_path):
    """发行包空库从初始迁移升级，不重复添加当前 ORM 已创建的列。"""
    configuration = Config(str(Path(__file__).resolve().parents[1] / 'backend/alembic.ini'))
    database_url = f'sqlite:///{(tmp_path / "fresh.db").as_posix()}'
    configuration.set_main_option('sqlalchemy.url', database_url)
    command.upgrade(configuration, 'head')
    engine = sa.create_engine(database_url)
    try:
        columns = sa.inspect(engine).get_columns('auth_users')
        column = next(item for item in columns if item['name'] == 'allowed_pages_json')
        assert column['nullable']
        assert isinstance(column['type'], sa.JSON)
        with engine.connect() as connection:
            version = sa.Table('alembic_version', sa.MetaData(), autoload_with=connection)
            assert connection.execute(sa.select(version.c.version_num)).scalar_one() == 'f2b7d9a4c6e8'
        command.upgrade(configuration, 'head')
    finally:
        engine.dispose()


def test_page_column_preserves_old_users_and_rejects_lossy_downgrade(tmp_path):
    """旧行升级为空，显式空页面同样不能在降级时丢弃。"""
    migration = importlib.import_module('backend.alembic.versions.f2b7d9a4c6e8_add_user_page_access')
    engine = sa.create_engine(f'sqlite:///{tmp_path / "migration.db"}')
    try:
        with engine.begin() as connection:
            metadata = sa.MetaData()
            users = sa.Table('auth_users', metadata, sa.Column('id', sa.Integer, primary_key=True))
            metadata.create_all(connection)
            connection.execute(users.insert().values(id=1))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                current = sa.Table('auth_users', sa.MetaData(), autoload_with=connection)
                assert connection.execute(sa.select(current.c.allowed_pages_json)).scalar() is None
                connection.execute(current.update().values(allowed_pages_json=[]))
                with pytest.raises(RuntimeError, match='不能降级'):
                    migration.downgrade()
                connection.execute(current.update().values(allowed_pages_json=sa.null()))
                migration.downgrade()
                assert 'allowed_pages_json' not in [c['name'] for c in sa.inspect(connection).get_columns('auth_users')]
    finally:
        engine.dispose()


def test_two_concurrent_admin_changes_cannot_remove_every_administrator(tmp_path):
    """两个独立事务同时撤销管理能力，只允许其中一个成功。"""
    client, factory = _create_local_auth_test_client(tmp_path, database_name='admin-race.db')
    try:
        with client:
            first = client.post('/api/v1/auth/bootstrap-admin', json={'username': 'admin-a', 'password': 'Admin12345'}).json()
            second = client.post('/api/v1/auth/users', headers={'Authorization': 'Bearer ' + first['access_token']}, json={'username': 'admin-b', 'password': 'Admin12345', 'scopes': ['*']}).json()['user']
            barrier = Barrier(2)
            def revoke(user_id):
                """在独立 Session 中同时更新，不共享进程内授权锁。"""
                service = LocalAuthService(settings=BackendServiceSettings(), session_factory=factory)
                barrier.wait(timeout=10)
                try:
                    service.update_user(user_id, LocalAuthUserUpdateRequest(scopes=()))
                    return 200
                except ServiceError as error:
                    return error.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(revoke, [first['user']['user_id'], second['user_id']]))
            assert sorted(results) == [200, 403]
    finally:
        factory.engine.dispose()
