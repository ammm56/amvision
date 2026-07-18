"""DatasetVersion 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.datasets.dataset_version import (
    ClassificationAnnotation,
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
    InstanceSegmentationAnnotation,
    ObbAnnotation,
    PoseAnnotation,
)
from backend.service.domain.datasets.dataset_version_summary import DatasetVersionSummary
from backend.service.infrastructure.persistence.dataset_orm import (
    DatasetAnnotationRecord,
    DatasetCategoryRecord,
    DatasetSampleRecord,
    DatasetVersionRecord,
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
            existing_record = self.session.get(
                DatasetVersionRecord,
                dataset_version.dataset_version_id,
            )
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
        """按 id 读取一个 DatasetVersion 聚合。"""

        statement = (
            select(DatasetVersionRecord)
            .options(
                selectinload(DatasetVersionRecord.categories),
                selectinload(DatasetVersionRecord.samples).selectinload(
                    DatasetSampleRecord.annotations
                ),
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
        """按 Dataset id 列出所有版本。"""

        statement = (
            select(DatasetVersionRecord)
            .options(
                selectinload(DatasetVersionRecord.categories),
                selectinload(DatasetVersionRecord.samples).selectinload(
                    DatasetSampleRecord.annotations
                ),
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

    def list_project_dataset_version_summaries(
        self,
        project_id: str,
    ) -> tuple[DatasetVersionSummary, ...]:
        """按 Project id 列出轻量摘要，不加载 samples 和 annotations。"""

        version_statement = (
            select(
                DatasetVersionRecord.dataset_version_id,
                DatasetVersionRecord.dataset_id,
                DatasetVersionRecord.project_id,
                DatasetVersionRecord.task_type,
                DatasetVersionRecord.metadata_json,
            )
            .where(DatasetVersionRecord.project_id == project_id)
            .order_by(DatasetVersionRecord.dataset_version_id.desc())
        )
        try:
            version_rows = self.session.execute(version_statement).all()
            version_ids = tuple(str(row.dataset_version_id) for row in version_rows)
            if not version_ids:
                return ()

            category_rows = self.session.execute(
                select(
                    DatasetCategoryRecord.dataset_version_id,
                    func.count(DatasetCategoryRecord.category_id),
                )
                .where(DatasetCategoryRecord.dataset_version_id.in_(version_ids))
                .group_by(DatasetCategoryRecord.dataset_version_id)
            ).all()
            sample_rows = self.session.execute(
                select(
                    DatasetSampleRecord.dataset_version_id,
                    DatasetSampleRecord.split,
                    func.count(DatasetSampleRecord.sample_id),
                )
                .where(DatasetSampleRecord.dataset_version_id.in_(version_ids))
                .group_by(DatasetSampleRecord.dataset_version_id, DatasetSampleRecord.split)
            ).all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 Project DatasetVersion 摘要失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        category_counts = {
            str(dataset_version_id): int(category_count)
            for dataset_version_id, category_count in category_rows
        }
        sample_counts: dict[str, int] = {}
        split_names_by_version: dict[str, set[str]] = {}
        for dataset_version_id, split_name, sample_count in sample_rows:
            normalized_version_id = str(dataset_version_id)
            sample_counts[normalized_version_id] = (
                sample_counts.get(normalized_version_id, 0) + int(sample_count)
            )
            split_names_by_version.setdefault(normalized_version_id, set()).add(
                str(split_name)
            )

        split_order = ("train", "val", "test")
        return tuple(
            DatasetVersionSummary(
                dataset_version_id=str(row.dataset_version_id),
                dataset_id=str(row.dataset_id),
                project_id=str(row.project_id),
                task_type=str(row.task_type),
                sample_count=sample_counts.get(str(row.dataset_version_id), 0),
                category_count=category_counts.get(str(row.dataset_version_id), 0),
                split_names=tuple(
                    split_name
                    for split_name in split_order
                    if split_name
                    in split_names_by_version.get(str(row.dataset_version_id), set())
                ),
                metadata=dict(row.metadata_json or {}),
            )
            for row in version_rows
        )

    def _to_record(self, dataset_version: DatasetVersion) -> DatasetVersionRecord:
        """把领域对象转换为 ORM 实体。"""

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
                        self._build_annotation_record(
                            sample_id=sample.sample_id,
                            annotation=annotation,
                        )
                        for annotation in sample.annotations
                    ],
                )
                for sample in dataset_version.samples
            ],
        )

    def _to_domain(self, record: DatasetVersionRecord) -> DatasetVersion:
        """把 ORM 实体转换为领域对象。"""

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
                        self._build_annotation_domain(annotation)
                        for annotation in sample.annotations
                    ),
                )
                for sample in record.samples
            ),
        )

    def _build_annotation_record(
        self,
        *,
        sample_id: str,
        annotation: DetectionAnnotation
        | InstanceSegmentationAnnotation
        | PoseAnnotation
        | ClassificationAnnotation
        | ObbAnnotation,
    ) -> DatasetAnnotationRecord:
        """把领域标注转换为统一 ORM annotation 实体。"""

        common = {
            "annotation_id": annotation.annotation_id,
            "sample_id": sample_id,
            "category_id": annotation.category_id,
            "metadata_json": dict(annotation.metadata),
        }
        if isinstance(annotation, ClassificationAnnotation):
            return DatasetAnnotationRecord(
                annotation_type="classification",
                bbox_x=None,
                bbox_y=None,
                bbox_w=None,
                bbox_h=None,
                segmentation_json=None,
                keypoints_json=None,
                num_keypoints=0,
                polygon_xy_json=None,
                iscrowd=0,
                area=None,
                **common,
            )
        if isinstance(annotation, InstanceSegmentationAnnotation):
            return DatasetAnnotationRecord(
                annotation_type="segmentation",
                bbox_x=annotation.bbox_xywh[0],
                bbox_y=annotation.bbox_xywh[1],
                bbox_w=annotation.bbox_xywh[2],
                bbox_h=annotation.bbox_xywh[3],
                segmentation_json=annotation.segmentation,
                keypoints_json=None,
                num_keypoints=0,
                polygon_xy_json=None,
                iscrowd=annotation.iscrowd,
                area=annotation.area,
                **common,
            )
        if isinstance(annotation, PoseAnnotation):
            return DatasetAnnotationRecord(
                annotation_type="pose",
                bbox_x=annotation.bbox_xywh[0],
                bbox_y=annotation.bbox_xywh[1],
                bbox_w=annotation.bbox_xywh[2],
                bbox_h=annotation.bbox_xywh[3],
                segmentation_json=None,
                keypoints_json=annotation.keypoints,
                num_keypoints=annotation.num_keypoints,
                polygon_xy_json=None,
                iscrowd=annotation.iscrowd,
                area=annotation.area,
                **common,
            )
        if isinstance(annotation, ObbAnnotation):
            return DatasetAnnotationRecord(
                annotation_type="obb",
                bbox_x=annotation.bbox_xywh[0],
                bbox_y=annotation.bbox_xywh[1],
                bbox_w=annotation.bbox_xywh[2],
                bbox_h=annotation.bbox_xywh[3],
                segmentation_json=None,
                keypoints_json=None,
                num_keypoints=0,
                polygon_xy_json=(
                    list(annotation.polygon_xy)
                    if annotation.polygon_xy is not None
                    else None
                ),
                iscrowd=annotation.iscrowd,
                area=annotation.area,
                **common,
            )
        return DatasetAnnotationRecord(
            annotation_type="detection",
            bbox_x=annotation.bbox_xywh[0],
            bbox_y=annotation.bbox_xywh[1],
            bbox_w=annotation.bbox_xywh[2],
            bbox_h=annotation.bbox_xywh[3],
            segmentation_json=None,
            keypoints_json=None,
            num_keypoints=0,
            polygon_xy_json=None,
            iscrowd=annotation.iscrowd,
            area=annotation.area,
            **common,
        )

    def _build_annotation_domain(
        self,
        annotation: DatasetAnnotationRecord,
    ) -> DetectionAnnotation | InstanceSegmentationAnnotation | PoseAnnotation | ClassificationAnnotation | ObbAnnotation:
        """把统一 ORM annotation 实体转换为领域对象。"""

        annotation_type = (annotation.annotation_type or "detection").strip() or "detection"
        metadata = dict(annotation.metadata_json or {})
        if annotation_type == "classification":
            return ClassificationAnnotation(
                annotation_id=annotation.annotation_id,
                category_id=annotation.category_id,
                metadata=metadata,
            )

        bbox = self._require_bbox(annotation)
        if annotation_type == "segmentation":
            segmentation = (
                annotation.segmentation_json
                if isinstance(annotation.segmentation_json, (list, dict))
                else None
            )
            return InstanceSegmentationAnnotation(
                annotation_id=annotation.annotation_id,
                category_id=annotation.category_id,
                bbox_xywh=bbox,
                segmentation=segmentation,
                iscrowd=annotation.iscrowd,
                area=annotation.area,
                metadata=metadata,
            )
        if annotation_type == "pose":
            keypoints = (
                annotation.keypoints_json
                if isinstance(annotation.keypoints_json, list)
                else None
            )
            return PoseAnnotation(
                annotation_id=annotation.annotation_id,
                category_id=annotation.category_id,
                bbox_xywh=bbox,
                keypoints=keypoints,
                num_keypoints=annotation.num_keypoints,
                iscrowd=annotation.iscrowd,
                area=annotation.area,
                metadata=metadata,
            )
        if annotation_type == "obb":
            polygon_xy = (
                tuple(float(value) for value in annotation.polygon_xy_json)
                if isinstance(annotation.polygon_xy_json, list)
                else None
            )
            return ObbAnnotation(
                annotation_id=annotation.annotation_id,
                category_id=annotation.category_id,
                bbox_xywh=bbox,
                polygon_xy=polygon_xy,
                iscrowd=annotation.iscrowd,
                area=annotation.area,
                metadata=metadata,
            )
        return DetectionAnnotation(
            annotation_id=annotation.annotation_id,
            category_id=annotation.category_id,
            bbox_xywh=bbox,
            iscrowd=annotation.iscrowd,
            area=annotation.area,
            metadata=metadata,
        )

    def _require_bbox(
        self,
        annotation: DatasetAnnotationRecord,
    ) -> tuple[float, float, float, float]:
        """从 ORM 标注实体中读取 bbox。"""

        if (
            annotation.bbox_x is None
            or annotation.bbox_y is None
            or annotation.bbox_w is None
            or annotation.bbox_h is None
        ):
            raise PersistenceOperationError(
                "数据集标注缺少 bbox",
                details={
                    "annotation_id": annotation.annotation_id,
                    "annotation_type": annotation.annotation_type,
                },
            )
        return (
            annotation.bbox_x,
            annotation.bbox_y,
            annotation.bbox_w,
            annotation.bbox_h,
        )
