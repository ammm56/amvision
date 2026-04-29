"""DatasetImport 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.datasets.dataset_import import DatasetImport
from backend.service.infrastructure.persistence.dataset_import_orm import DatasetImportRecord


class SqlAlchemyDatasetImportRepository:
    """使用 SQLAlchemy 持久化 DatasetImport。"""

    def __init__(self, session: Session) -> None:
        """初始化 DatasetImport 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_dataset_import(self, dataset_import: DatasetImport) -> None:
        """保存一个 DatasetImport。

        参数：
        - dataset_import：要保存的 DatasetImport。
        """

        try:
            existing_record = self.session.get(DatasetImportRecord, dataset_import.dataset_import_id)
            if existing_record is None:
                self.session.add(self._to_record(dataset_import))
                return

            existing_record.dataset_id = dataset_import.dataset_id
            existing_record.project_id = dataset_import.project_id
            existing_record.format_type = dataset_import.format_type
            existing_record.task_type = dataset_import.task_type
            existing_record.status = dataset_import.status
            existing_record.created_at = dataset_import.created_at
            existing_record.dataset_version_id = dataset_import.dataset_version_id
            existing_record.package_path = dataset_import.package_path
            existing_record.staging_path = dataset_import.staging_path
            existing_record.version_path = dataset_import.version_path
            existing_record.image_root = dataset_import.image_root
            existing_record.annotation_root = dataset_import.annotation_root
            existing_record.manifest_file = dataset_import.manifest_file
            existing_record.split_strategy = dataset_import.split_strategy
            existing_record.class_map_json = dict(dataset_import.class_map)
            existing_record.detected_profile_json = dict(dataset_import.detected_profile)
            existing_record.validation_report_json = dict(dataset_import.validation_report)
            existing_record.error_message = dataset_import.error_message
            existing_record.metadata_json = dict(dataset_import.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 DatasetImport 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_dataset_import(self, dataset_import_id: str) -> DatasetImport | None:
        """按 id 读取一个 DatasetImport。

        参数：
        - dataset_import_id：DatasetImport id。

        返回：
        - 读取到的 DatasetImport；不存在时返回 None。
        """

        try:
            record = self.session.get(DatasetImportRecord, dataset_import_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 DatasetImport 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_domain(record)

    def list_dataset_imports(self, dataset_id: str) -> tuple[DatasetImport, ...]:
        """按 Dataset id 列出导入记录。

        参数：
        - dataset_id：Dataset id。

        返回：
        - 该 Dataset 下的 DatasetImport 列表。
        """

        statement = (
            select(DatasetImportRecord)
            .where(DatasetImportRecord.dataset_id == dataset_id)
            .order_by(DatasetImportRecord.created_at, DatasetImportRecord.dataset_import_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 DatasetImport 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_domain(record) for record in records)

    def _to_record(self, dataset_import: DatasetImport) -> DatasetImportRecord:
        """把领域对象转换为 ORM 实体。

        参数：
        - dataset_import：要转换的领域对象。

        返回：
        - 对应的 ORM 实体。
        """

        return DatasetImportRecord(
            dataset_import_id=dataset_import.dataset_import_id,
            dataset_id=dataset_import.dataset_id,
            project_id=dataset_import.project_id,
            format_type=dataset_import.format_type,
            task_type=dataset_import.task_type,
            status=dataset_import.status,
            created_at=dataset_import.created_at,
            dataset_version_id=dataset_import.dataset_version_id,
            package_path=dataset_import.package_path,
            staging_path=dataset_import.staging_path,
            version_path=dataset_import.version_path,
            image_root=dataset_import.image_root,
            annotation_root=dataset_import.annotation_root,
            manifest_file=dataset_import.manifest_file,
            split_strategy=dataset_import.split_strategy,
            class_map_json=dict(dataset_import.class_map),
            detected_profile_json=dict(dataset_import.detected_profile),
            validation_report_json=dict(dataset_import.validation_report),
            error_message=dataset_import.error_message,
            metadata_json=dict(dataset_import.metadata),
        )

    def _to_domain(self, record: DatasetImportRecord) -> DatasetImport:
        """把 ORM 实体转换为领域对象。

        参数：
        - record：要转换的 ORM 实体。

        返回：
        - 对应的 DatasetImport 领域对象。
        """

        return DatasetImport(
            dataset_import_id=record.dataset_import_id,
            dataset_id=record.dataset_id,
            project_id=record.project_id,
            format_type=record.format_type,
            task_type=record.task_type,
            status=record.status,
            created_at=record.created_at,
            dataset_version_id=record.dataset_version_id,
            package_path=record.package_path,
            staging_path=record.staging_path,
            version_path=record.version_path,
            image_root=record.image_root,
            annotation_root=record.annotation_root,
            manifest_file=record.manifest_file,
            split_strategy=record.split_strategy,
            class_map=dict(record.class_map_json or {}),
            detected_profile=dict(record.detected_profile_json or {}),
            validation_report=dict(record.validation_report_json or {}),
            error_message=record.error_message,
            metadata=dict(record.metadata_json or {}),
        )