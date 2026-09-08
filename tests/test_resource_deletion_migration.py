"""资源删除表从热重载中间结构升级的回归测试。"""

from datetime import datetime
from importlib import import_module
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.service.domain.resource_deletion import ResourceDeletionPlan, ResourceRef
from backend.service.infrastructure.persistence.resource_deletion_repository import (
    ResourceDeletionRepository,
)


@pytest.mark.parametrize("existing_table", [False, True])
def test_resource_deletion_migration_preserves_legacy_plan(
    tmp_path: Path, existing_table: bool
) -> None:
    """新库和缺少 updated_at 的旧表均可升级，并保持清单和索引完整。"""
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    migration = import_module(
        "backend.alembic.versions.c5e7f9a1b3d6_add_resource_deletions"
    )
    metadata = sa.MetaData()
    legacy = sa.Table(
        "resource_deletions",
        metadata,
        sa.Column("operation_id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(2048)),
    )
    plan = ResourceDeletionPlan(
        operation_id="pending-test",
        project_id="test-project",
        target=ResourceRef(kind="task", resource_id="test-task"),
        paths=[{"source": "task-runs/test", "staged": "runtime/test-staging"}],
    ).model_dump(mode="json")
    try:
        with engine.begin() as connection:
            if existing_table:
                metadata.create_all(connection)
                connection.execute(
                    legacy.insert().values(
                        operation_id="pending-test",
                        project_id="test-project",
                        state="committed",
                        plan_json=plan,
                        error="file occupied",
                    )
                )
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
            inspector = sa.inspect(connection)
            columns = {
                item["name"]: item
                for item in inspector.get_columns("resource_deletions")
            }
            assert columns["updated_at"]["nullable"] is False
            assert {
                item["name"] for item in inspector.get_indexes("resource_deletions")
            } == {
                "ix_resource_deletions_project_id",
                "ix_resource_deletions_state",
                "ix_resource_deletions_updated_at",
            }
            table = sa.Table(
                "resource_deletions", sa.MetaData(), autoload_with=connection
            )
            rows = connection.execute(sa.select(table)).mappings().all()
            assert len(rows) == int(existing_table)
            if existing_table:
                assert rows[0]["plan_json"] == plan
                assert rows[0]["state"] == "committed"
                assert rows[0]["error"] == "file occupied"
                assert datetime.fromisoformat(rows[0]["updated_at"]).tzinfo is not None
            # 回归日志中实际失败的 ORM 恢复查询，而不只检查表结构。
            with Session(bind=connection) as session:
                pending = ResourceDeletionRepository(session).list_pending()
                assert len(pending) == int(existing_table)
                if existing_table:
                    assert pending[0].plan.model_dump(mode="json") == plan
    finally:
        engine.dispose()
