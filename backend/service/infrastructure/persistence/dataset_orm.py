"""DatasetVersion 聚合的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.service.infrastructure.persistence.base import Base


class DatasetVersionRecord(Base):
    """映射 DatasetVersion 聚合根。"""

    __tablename__ = "dataset_versions"

    dataset_version_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    task_type: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    categories: Mapped[list[DatasetCategoryRecord]] = relationship(
        back_populates="dataset_version",
        cascade="all, delete-orphan",
        order_by="DatasetCategoryRecord.category_id",
    )
    samples: Mapped[list[DatasetSampleRecord]] = relationship(
        back_populates="dataset_version",
        cascade="all, delete-orphan",
        order_by="DatasetSampleRecord.image_id",
    )


class DatasetCategoryRecord(Base):
    """映射 DatasetVersion 中的类别对象。"""

    __tablename__ = "dataset_categories"

    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.dataset_version_id", ondelete="CASCADE"),
        primary_key=True,
    )
    category_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))

    dataset_version: Mapped[DatasetVersionRecord] = relationship(back_populates="categories")


class DatasetSampleRecord(Base):
    """映射 DatasetVersion 中的样本对象。"""

    __tablename__ = "dataset_samples"

    sample_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.dataset_version_id", ondelete="CASCADE"),
        index=True,
    )
    image_id: Mapped[int] = mapped_column(Integer)
    file_name: Mapped[str] = mapped_column(String(512))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    split: Mapped[str] = mapped_column(String(32))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    dataset_version: Mapped[DatasetVersionRecord] = relationship(back_populates="samples")
    annotations: Mapped[list[DetectionAnnotationRecord]] = relationship(
        back_populates="sample",
        cascade="all, delete-orphan",
        order_by="DetectionAnnotationRecord.annotation_id",
    )


class DetectionAnnotationRecord(Base):
    """映射 detection annotation 对象。"""

    __tablename__ = "dataset_detection_annotations"

    annotation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_samples.sample_id", ondelete="CASCADE"),
        index=True,
    )
    category_id: Mapped[int] = mapped_column(Integer)
    bbox_x: Mapped[float] = mapped_column(Float)
    bbox_y: Mapped[float] = mapped_column(Float)
    bbox_w: Mapped[float] = mapped_column(Float)
    bbox_h: Mapped[float] = mapped_column(Float)
    iscrowd: Mapped[int] = mapped_column(Integer, default=0)
    area: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    sample: Mapped[DatasetSampleRecord] = relationship(back_populates="annotations")