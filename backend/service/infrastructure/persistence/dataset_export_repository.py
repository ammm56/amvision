"""DatasetExport 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.persistence.dataset_export_orm import DatasetExportRecord


class SqlAlchemyDatasetExportRepository:
    """使用 SQLAlchemy 持久化 DatasetExport。"""

    def __init__(self, session: Session) -> None:
        """初始化 DatasetExport 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_dataset_export(self, dataset_export: DatasetExport) -> None:
        """保存一个 DatasetExport。

        参数：
        - dataset_export：要保存的 DatasetExport。
        """

        try:
            existing_record = self.session.get(DatasetExportRecord, dataset_export.dataset_export_id)
            if existing_record is None:
                self.session.add(self._to_record(dataset_export))
                return

            existing_record.dataset_id = dataset_export.dataset_id
            existing_record.project_id = dataset_export.project_id
            existing_record.dataset_version_id = dataset_export.dataset_version_id
            existing_record.format_id = dataset_export.format_id
            existing_record.task_type = dataset_export.task_type
            existing_record.status = dataset_export.status
            existing_record.created_at = dataset_export.created_at
            existing_record.task_id = dataset_export.task_id
            existing_record.include_test_split = dataset_export.include_test_split
            existing_record.export_path = dataset_export.export_path
            existing_record.manifest_object_key = dataset_export.manifest_object_key
            existing_record.split_names_json = list(dataset_export.split_names)
            existing_record.sample_count = dataset_export.sample_count
            existing_record.category_names_json = list(dataset_export.category_names)
            existing_record.error_message = dataset_export.error_message
            existing_record.metadata_json = dict(dataset_export.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 DatasetExport 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_dataset_export(self, dataset_export_id: str) -> DatasetExport | None:
        """按 id 读取一个 DatasetExport。

        参数：
        - dataset_export_id：DatasetExport id。

        返回：
        - 读取到的 DatasetExport；不存在时返回 None。
        """

        try:
            record = self.session.get(DatasetExportRecord, dataset_export_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 DatasetExport 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_domain(record)

    def list_dataset_exports(self, dataset_version_id: str) -> tuple[DatasetExport, ...]:
        """按 DatasetVersion id 列出导出记录。

        参数：
        - dataset_version_id：DatasetVersion id。

        返回：
        - 该 DatasetVersion 下的 DatasetExport 列表。
        """

        statement = (
            select(DatasetExportRecord)
            .where(DatasetExportRecord.dataset_version_id == dataset_version_id)
            .order_by(DatasetExportRecord.created_at, DatasetExportRecord.dataset_export_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 DatasetExport 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_domain(record) for record in records)

    def _to_record(self, dataset_export: DatasetExport) -> DatasetExportRecord:
        """把领域对象转换为 ORM 实体。"""

        return DatasetExportRecord(
            dataset_export_id=dataset_export.dataset_export_id,
            dataset_id=dataset_export.dataset_id,
            project_id=dataset_export.project_id,
            dataset_version_id=dataset_export.dataset_version_id,
            format_id=dataset_export.format_id,
            task_type=dataset_export.task_type,
            status=dataset_export.status,
            created_at=dataset_export.created_at,
            task_id=dataset_export.task_id,
            include_test_split=dataset_export.include_test_split,
            export_path=dataset_export.export_path,
            manifest_object_key=dataset_export.manifest_object_key,
            split_names_json=list(dataset_export.split_names),
            sample_count=dataset_export.sample_count,
            category_names_json=list(dataset_export.category_names),
            error_message=dataset_export.error_message,
            metadata_json=dict(dataset_export.metadata),
        )

    def _to_domain(self, record: DatasetExportRecord) -> DatasetExport:
        """把 ORM 实体转换为领域对象。"""

        return DatasetExport(
            dataset_export_id=record.dataset_export_id,
            dataset_id=record.dataset_id,
            project_id=record.project_id,
            dataset_version_id=record.dataset_version_id,
            format_id=record.format_id,
            task_type=record.task_type,
            status=record.status,
            created_at=record.created_at,
            task_id=record.task_id,
            include_test_split=record.include_test_split,
            export_path=record.export_path,
            manifest_object_key=record.manifest_object_key,
            split_names=tuple(record.split_names_json or []),
            sample_count=record.sample_count,
            category_names=tuple(record.category_names_json or []),
            error_message=record.error_message,
            metadata=dict(record.metadata_json or {}),
        )