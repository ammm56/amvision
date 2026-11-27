"""批量异步推理任务 API 请求与响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.service.infrastructure.persistence.batch_inference_task_orm import (
    BatchInferenceTaskItemRecord,
    BatchInferenceTaskRecord,
)


class BatchInferenceTaskCreateJsonBody(BaseModel):
    """创建批量推理任务的 JSON 请求体（支持数据集版本与项目文件来源）。"""

    project_id: str = Field(description="所属 Project id")
    task_type: str = Field(description="任务类型")
    deployment_instance_id: str = Field(description="部署实例 id（支持 running 状态的 async 或 sync 通道）")
    runtime_mode: Literal["auto", "async", "sync"] = Field(
        default="auto",
        description="执行通道；auto 优先 async，否则回退 sync；也可显式指定 async 或 sync",
    )
    display_name: str = Field(default="", description="批量任务名称")
    source_kind: Literal["dataset_version", "project_files"] = Field(
        description="输入来源类型"
    )
    dataset_id: str | None = Field(default=None, description="数据集 id")
    dataset_version_id: str | None = Field(default=None, description="数据集版本 id")
    dataset_split: str = Field(default="", description="数据集划分（可选）")
    sample_ids: list[str] = Field(default_factory=list, description="可选指定样本 id 列表")
    input_file_ids: list[str] = Field(default_factory=list, description="Project 公开文件 id 列表")
    score_threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="置信度阈值")
    top_k: int = Field(default=5, ge=1, le=100, description="分类 Top-K")
    mask_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Mask 阈值")
    keypoint_confidence_threshold: float = Field(
        default=0.3, ge=0.0, le=1.0, description="关键点置信度阈值"
    )
    save_result_image: bool = Field(default=True, description="是否生成并保存预览图")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")


class BatchInferenceTaskResponse(BaseModel):
    """批量推理主任务摘要与详情响应。"""

    batch_task_id: str
    project_id: str
    task_type: str
    display_name: str
    deployment_instance_id: str
    deployment_display_name: str
    model_version_id: str | None = None
    model_build_id: str | None = None
    source_kind: str
    source_summary: dict[str, object] = Field(default_factory=dict)
    parameters: dict[str, object] = Field(default_factory=dict)
    state: str
    total_items: int
    completed_items: int
    succeeded_items: int
    failed_items: int
    skipped_items: int
    output_object_prefix: str
    error_message: str | None = None
    created_by: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str


class BatchInferenceTaskItemResponse(BaseModel):
    """批量推理单图子项响应。"""

    item_id: str
    batch_task_id: str
    sequence_no: int
    input_label: str
    input_source_kind: str
    input_file_id: str | None = None
    input_uri: str | None = None
    has_input_image: bool
    has_preview_image: bool
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    sample_id: str | None = None
    state: str
    item_count: int | None = None
    latency_ms: float | None = None
    image_width: int | None = None
    image_height: int | None = None
    result_object_key: str | None = None
    preview_image_object_key: str | None = None
    result_summary: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class BatchInferenceTaskItemResultResponse(BaseModel):
    """单图子项完整推理结果载荷响应。"""

    file_status: Literal["pending", "ready", "missing"]
    item_state: str
    object_key: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


def build_batch_inference_task_response(
    task: BatchInferenceTaskRecord,
) -> BatchInferenceTaskResponse:
    """将批量主任务 ORM 记录转换为响应对象。"""

    return BatchInferenceTaskResponse(
        batch_task_id=task.batch_task_id,
        project_id=task.project_id,
        task_type=task.task_type,
        display_name=task.display_name,
        deployment_instance_id=task.deployment_instance_id,
        deployment_display_name=task.deployment_display_name,
        model_version_id=task.model_version_id,
        model_build_id=task.model_build_id,
        source_kind=task.source_kind,
        source_summary=dict(task.source_summary_json or {}),
        parameters=dict(task.parameters_json or {}),
        state=task.state,
        total_items=task.total_items,
        completed_items=task.completed_items,
        succeeded_items=task.succeeded_items,
        failed_items=task.failed_items,
        skipped_items=task.skipped_items,
        output_object_prefix=task.output_object_prefix,
        error_message=task.error_message,
        created_by=task.created_by,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        updated_at=task.updated_at,
    )


def build_batch_inference_task_item_response(
    item: BatchInferenceTaskItemRecord,
) -> BatchInferenceTaskItemResponse:
    """将批量单图子项 ORM 记录转换为响应对象。"""

    return BatchInferenceTaskItemResponse(
        item_id=item.item_id,
        batch_task_id=item.batch_task_id,
        sequence_no=item.sequence_no,
        input_label=item.input_label,
        input_source_kind=item.input_source_kind,
        input_file_id=item.input_file_id,
        input_uri=item.input_uri,
        has_input_image=bool(item.input_image_object_key),
        has_preview_image=bool(item.preview_image_object_key),
        dataset_id=item.dataset_id,
        dataset_version_id=item.dataset_version_id,
        sample_id=item.sample_id,
        state=item.state,
        item_count=item.item_count,
        latency_ms=item.latency_ms,
        image_width=item.image_width,
        image_height=item.image_height,
        result_object_key=item.result_object_key,
        preview_image_object_key=item.preview_image_object_key,
        result_summary=dict(item.result_summary_json or {}),
        error_code=item.error_code,
        error_message=item.error_message,
        started_at=item.started_at,
        finished_at=item.finished_at,
    )
