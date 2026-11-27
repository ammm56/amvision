"""同步推理显式保存记录的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class DirectInferenceRecord(Base):
    """映射一次显式保存的同步推理历史记录。

    字段：
    - record_id：记录主键 id。
    - project_id：所属 Project id。
    - request_id：客户端或网关关联的同步请求 id，同一 Project 内唯一。
    - task_type：模型任务类型（detection/classification/segmentation/pose/obb）。
    - deployment_instance_id：执行推理的 DeploymentInstance id。
    - deployment_display_name：保存时快照的 DeploymentInstance 名称。
    - model_version_id：模型版本 id。
    - model_build_id：模型构建版本 id。
    - input_source_kind：输入来源类型。
    - input_label：界面展示用的输入名称。
    - input_uri：原始输入 URI 或 object key。
    - input_file_id：Project 公开文件 id。
    - input_image_object_key：随记录落盘的输入图片 object key。
    - preview_image_object_key：随记录落盘的预览图 object key。
    - result_object_key：推理结果 JSON 文件的 object key。
    - output_object_prefix：当前记录产物根目录前缀。
    - item_count：检测对象或分类项数量。
    - latency_ms：总耗时（毫秒）。
    - image_width：输入图像宽度。
    - image_height：输入图像高度。
    - parameters_json：当次推理参数快照。
    - result_summary_json：结构化结果摘要。
    - created_by：创建主体 id。
    - created_at：ISO8601 UTC 创建时间。
    """

    __tablename__ = "direct_inference_records"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "request_id",
            name="uq_direct_inference_records_project_request",
        ),
    )

    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    deployment_instance_id: Mapped[str] = mapped_column(String(128), index=True)
    deployment_display_name: Mapped[str] = mapped_column(String(255), default="")
    model_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_build_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_source_kind: Mapped[str] = mapped_column(String(64), default="")
    input_label: Mapped[str] = mapped_column(String(512), default="")
    input_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    input_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    input_image_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    preview_image_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    result_object_key: Mapped[str] = mapped_column(String(1024))
    output_object_prefix: Mapped[str] = mapped_column(String(1024))
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
