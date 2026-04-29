"""DatasetVersion 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
)
from backend.service.infrastructure.persistence.dataset_orm import (
    DatasetCategoryRecord,
    DatasetSampleRecord,
    DatasetVersionRecord,
    DetectionAnnotationRecord,
)


class SqlAlchemyDatasetVersionRepository:
    """使用 SQLAlchemy 持久化 DatasetVersion 聚合。"""

    def __init__(self, session: Session) -> None:
        """初始化 DatasetVersion 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_dataset_version(self, dataset_version: DatasetVersion) -> None:
        """保存一个 DatasetVersion 聚合。

        参数：
        - dataset_version：要保存的 DatasetVersion。
        """

        try:
            existing_record = self.session.get(DatasetVersionRecord, dataset_version.dataset_version_id)
            if existing_record is not None:
                self.session.delete(existing_record)
                self.session.flush()

            self.session.add(self._to_record(dataset_version))
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 DatasetVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_dataset_version(self, dataset_version_id: str) -> DatasetVersion | None:
        """按 id 读取一个 DatasetVersion 聚合。

        参数：
        - dataset_version_id：DatasetVersion id。

        返回：
        - 读取到的 DatasetVersion；不存在时返回 None。
        """

        statement = (
            select(DatasetVersionRecord)
            .options(
                selectinload(DatasetVersionRecord.categories),
                selectinload(DatasetVersionRecord.samples).selectinload(DatasetSampleRecord.annotations),
            )
            .where(DatasetVersionRecord.dataset_version_id == dataset_version_id)
        )
        try:
            record = self.session.execute(statement).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 DatasetVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_domain(record)

    def list_dataset_versions(self, dataset_id: str) -> tuple[DatasetVersion, ...]:
        """按 Dataset id 列出所有版本。

        参数：
        - dataset_id：Dataset id。

        返回：
        - 该 Dataset 下的 DatasetVersion 列表。
        """

        statement = (
            select(DatasetVersionRecord)
            .options(
                selectinload(DatasetVersionRecord.categories),
                selectinload(DatasetVersionRecord.samples).selectinload(DatasetSampleRecord.annotations),
            )
            .where(DatasetVersionRecord.dataset_id == dataset_id)
            .order_by(DatasetVersionRecord.dataset_version_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 DatasetVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_domain(record) for record in records)

    def _to_record(self, dataset_version: DatasetVersion) -> DatasetVersionRecord:
        """把领域对象转换为 ORM 实体。

        参数：
        - dataset_version：要转换的领域对象。

        返回：
        - 对应的 ORM 聚合根实体。
        """

        return DatasetVersionRecord(
            dataset_version_id=dataset_version.dataset_version_id,
            dataset_id=dataset_version.dataset_id,
            project_id=dataset_version.project_id,
            task_type=dataset_version.task_type,
            metadata_json=dict(dataset_version.metadata),
            categories=[
                DatasetCategoryRecord(
                    dataset_version_id=dataset_version.dataset_version_id,
                    category_id=category.category_id,
                    name=category.name,
                )
                for category in dataset_version.categories
            ],
            samples=[
                DatasetSampleRecord(
                    sample_id=sample.sample_id,
                    dataset_version_id=dataset_version.dataset_version_id,
                    image_id=sample.image_id,
                    file_name=sample.file_name,
                    width=sample.width,
                    height=sample.height,
                    split=sample.split,
                    metadata_json=dict(sample.metadata),
                    annotations=[
                        DetectionAnnotationRecord(
                            annotation_id=annotation.annotation_id,
                            sample_id=sample.sample_id,
                            category_id=annotation.category_id,
                            bbox_x=annotation.bbox_xywh[0],
                            bbox_y=annotation.bbox_xywh[1],
                            bbox_w=annotation.bbox_xywh[2],
                            bbox_h=annotation.bbox_xywh[3],
                            iscrowd=annotation.iscrowd,
                            area=annotation.area,
                            metadata_json=dict(annotation.metadata),
                        )
                        for annotation in sample.annotations
                    ],
                )
                for sample in dataset_version.samples
            ],
        )

    def _to_domain(self, record: DatasetVersionRecord) -> DatasetVersion:
        """把 ORM 实体转换为领域对象。

        参数：
        - record：要转换的 ORM 聚合根实体。

        返回：
        - 对应的 DatasetVersion 领域对象。
        """

        return DatasetVersion(
            dataset_version_id=record.dataset_version_id,
            dataset_id=record.dataset_id,
            project_id=record.project_id,
            task_type=record.task_type,
            metadata=dict(record.metadata_json or {}),
            categories=tuple(
                DatasetCategory(category_id=category.category_id, name=category.name)
                for category in record.categories
            ),
            samples=tuple(
                DatasetSample(
                    sample_id=sample.sample_id,
                    image_id=sample.image_id,
                    file_name=sample.file_name,
                    width=sample.width,
                    height=sample.height,
                    split=sample.split,
                    metadata=dict(sample.metadata_json or {}),
                    annotations=tuple(
                        DetectionAnnotation(
                            annotation_id=annotation.annotation_id,
                            category_id=annotation.category_id,
                            bbox_xywh=(
                                annotation.bbox_x,
                                annotation.bbox_y,
                                annotation.bbox_w,
                                annotation.bbox_h,
                            ),
                            iscrowd=annotation.iscrowd,
                            area=annotation.area,
                            metadata=dict(annotation.metadata_json or {}),
                        )
                        for annotation in sample.annotations
                    ),
                )
                for sample in record.samples
            ),
        )