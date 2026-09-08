"""无主目录清理与数据库物理整理验收。"""

import sqlite3
import pytest

from backend.maintenance.database_compaction import compact_database
from backend.maintenance.resource_cleanup import scan_orphan_dataset_directories
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.settings import BackendServiceSettings
from tests import test_resource_deletion_service as deletion_fixtures

deletion_runtime = deletion_fixtures.deletion_runtime


def test_orphan_scan_preserves_references_and_cleanup_rechecks(deletion_runtime):
    """已扫描候选出现新引用时仍不能执行；无引用目录可完整清理。"""
    service, factory, storage, queue = deletion_runtime
    path = "projects/project-1/datasets/old-dataset/imports/old-import/file.bin"
    storage.write_bytes(path, b"old-data")
    candidates = scan_orphan_dataset_directories(factory, storage, queue, "project-1")
    assert len(candidates) == 1 and candidates[0].can_delete
    with factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        unit.tasks.save_task(
            TaskRecord(
                task_id="ref",
                project_id="project-1",
                task_kind="dataset-import",
                state="failed",
                task_spec={"dataset_import_id": "old-import"},
            )
        )
        unit.commit()
    from backend.service.application.errors import ResourceInUseError

    with pytest.raises(ResourceInUseError):
        service.delete(
            kind="dataset-import",
            resource_id="old-import",
            project_id="project-1",
            orphan_dataset_id="old-dataset",
        )
    assert storage.resolve(path).exists()
    with factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        unit.tasks.delete_task("ref")
        unit.commit()
    service.delete(
        kind="dataset-import",
        resource_id="old-import",
        project_id="project-1",
        orphan_dataset_id="old-dataset",
    )
    assert not storage.resolve(path).exists()
    assert scan_orphan_dataset_directories(factory, storage, queue, "project-1") == []


def test_sqlite_compaction_reclaims_space_and_keeps_rows(tmp_path):
    """业务删除释放页与 VACUUM 缩小文件分别验证，保留行不变。"""
    path = tmp_path / "compact.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE payloads (id INTEGER PRIMARY KEY, data BLOB)")
        connection.executemany(
            "INSERT INTO payloads(data) VALUES (?)", [(b"x" * 4096,)] * 500
        )
        connection.commit()
        connection.execute("DELETE FROM payloads WHERE id > 1")
    settings = BackendServiceSettings(database={"url": f"sqlite:///{path.as_posix()}"})
    result = compact_database(settings)
    assert result["before_free_pages"] > 0
    assert result["after_free_pages"] == 0
    assert result["after_bytes"] < result["before_bytes"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM payloads").fetchone()[0] == 1
