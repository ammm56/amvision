"""导出记录筛选在分页之前执行，不把已清理产物显示为可下载。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.service.infrastructure.persistence.base import Base
from backend.service.infrastructure.persistence.dataset_catalog_repository import DatasetCatalogRepository
from backend.service.infrastructure.persistence.dataset_export_orm import DatasetExportRecord


def test_export_record_filters(tmp_path):
    """覆盖未打包可下载、已清理、失败、处理中与文件名组合检索。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'records.db'}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            for identity, status, metadata in [
                ("a", "completed", {"package_file_name": "inspection.zip"}),
                ("b", "completed", {"files_cleaned_at": "2026-11-01"}),
                ("c", "failed", {}),
                ("d", "running", {}),
                ("e", "completed", {}),
            ]:
                session.add(DatasetExportRecord(dataset_export_id=identity, project_id="p", dataset_id="d", dataset_version_id="v", format_id="coco", task_type="detection", status=status, created_at="2026-11-01T00:00:00+00:00", metadata_json=metadata))
            session.commit()
            repository = DatasetCatalogRepository(session)
            ready = repository.records("p", "exports", file_state="ready", limit=1)
            assert ready["total"] == 2
            assert ready["items"][0].dataset_export_id == "a"
            assert repository.records("p", "exports", file_state="ready", offset=1, limit=1)["items"][0].dataset_export_id == "e"
            for state, identity in [("cleaned", "b"), ("not_generated", "c"), ("generating", "d")]:
                result = repository.records("p", "exports", file_state=state)
                assert result["total"] == 1
                assert result["items"][0].dataset_export_id == identity
            assert repository.records("p", "exports", q="inspection.zip", file_state="ready")["total"] == 1
            assert repository.records("p", "exports", q="inspection.zip", file_state="cleaned")["total"] == 0
            assert repository.records("p", "exports", created_after="2026-11-02")["total"] == 0
            assert repository.records("other", "exports", file_state="ready")["total"] == 0
    finally:
        engine.dispose()
