"""批量异步推理任务与单图子项的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.service.infrastructure.persistence.base import Base


class BatchInferenceTaskRecord(Base):
    """映射一条批量推理主任务。

    字段：
    - batch_task_id：批量任务主键 id。
    - project_id：所属 Project id。
    - task_type：模型任务类型（detection/classification/segmentation/pose/obb）。
    - display_name：批量任务展示名称。
    - deployment_instance_id：执行推理使用的 async DeploymentInstance id。
    - deployment_display_name：创建时快照的 DeploymentInstance 名称。
    - model_version_id：模型版本 id。
    - model_build_id：模型构建版本 id。
    - source_kind：批量输入来源（upload/dataset_version/project_files）。
    - source_summary_json：来源描述快照（如数据集 id/版本/split 或文件列表摘要）。
    - parameters_json：推理参数与保存选项快照。
    - state：任务状态（queued/running/succeeded/partial_failed/failed/cancelled）。
    - total_items：总图片数。
    - completed_items：已处理结束的图片数（成功 + 失败 + 跳过）。
    - succeeded_items：成功图片数。
    - failed_items：失败图片数。
    - skipped_items：跳过或取消未执行图片数。
    - output_object_prefix：当前批量任务产物根目录前缀。
    - error_message：主任务级失败信息。
    - created_by：创建主体 id。
    - created_at：ISO8601 UTC 创建时间。
    - started_at：开始执行时间。
    - finished_at：结束执行时间。
    - updated_at：最近更新时间。
    - items：关联的单图子项列表。
    """

    __tablename__ = "batch_inference_tasks"

    batch_task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    deployment_instance_id: Mapped[str] = mapped_column(String(128), index=True)
    deployment_display_name: Mapped[str] = mapped_column(String(255), default="")
    model_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_build_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(64), default="")
    source_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(32), index=True)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    skipped_items: Mapped[int] = mapped_column(Integer, default=0)
    output_object_prefix: Mapped[str] = mapped_column(String(1024))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)

    items: Mapped[list[BatchInferenceTaskItemRecord]] = relationship(
        back_populates="batch_task",
        cascade="all, delete-orphan",
        order_by="BatchInferenceTaskItemRecord.sequence_no",
    )


class BatchInferenceTaskItemRecord(Base):
    """映射批量推理任务中的单张图像子项。

    字段：
    - item_id：子项主键 id。
    - batch_task_id：所属批量任务 id。
    - sequence_no：在批量任务中的顺序序号（从 1 开始）。
    - input_label：展示用文件名或样本名。
    - input_source_kind：输入来源类型。
    - input_file_id：Project 公开文件 id。
    - input_uri：输入 object key 或 URI。
    - input_image_object_key：暂存或关联的可预览输入图 object key。
    - dataset_id：来自数据集时的 dataset id。
    - dataset_version_id：来自数据集时的 version id。
    - sample_id：来自数据集时的 sample id。
    - state：子项状态（pending/running/succeeded/failed/cancelled）。
    - child_task_id：可选关联的任务 id。
    - item_count：检测对象或分类项数量。
    - latency_ms：单图推理耗时（毫秒）。
    - image_width：图像宽度。
    - image_height：图像高度。
    - result_object_key：单图推理结果 JSON 的 object key。
    - preview_image_object_key：单图预览图的 object key。
    - result_summary_json：单图结构化摘要。
    - error_code：失败错误码。
    - error_message：失败原因描述。
    - started_at：子项开始时间。
    - finished_at：子项结束时间。
    """

    __tablename__ = "batch_inference_task_items"

    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_task_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("batch_inference_tasks.batch_task_id", ondelete="CASCADE"),
        index=True,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, default=0)
    input_label: Mapped[str] = mapped_column(String(512), default="")
    input_source_kind: Mapped[str] = mapped_column(String(64), default="")
    input_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    input_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    input_image_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dataset_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sample_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    child_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    preview_image_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    result_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    batch_task: Mapped[BatchInferenceTaskRecord] = relationship(back_populates="items")
