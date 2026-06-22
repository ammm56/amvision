"""segmentation evaluation 响应模型与构建函数。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SegmentationEvaluationSubmissionResponse(BaseModel):
    """描述 segmentation evaluation 提交响应。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_version_id: str
    model_version_id: str


class SegmentationEvaluationSummaryResponse(BaseModel):
    """描述 segmentation evaluation 摘要响应。"""

    task_id: str
    display_name: str
    project_id: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    map50: float | None = None
    map50_95: float | None = None
    mask_map50: float | None = None
    mask_map50_95: float | None = None
    sample_count: int | None = None


class SegmentationEvaluationDetailResponse(SegmentationEvaluationSummaryResponse):
    """描述 segmentation evaluation 详情响应。"""

    metadata: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)


def build_segmentation_evaluation_summary_response(task: object) -> SegmentationEvaluationSummaryResponse:
    """把任务记录转换成 segmentation evaluation 摘要响应。"""

    result = dict(task.result) if task.result else {}
    return SegmentationEvaluationSummaryResponse(
        task_id=task.task_id,
        display_name=task.display_name,
        project_id=task.project_id,
        state=task.state,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error_message=task.error_message,
        map50=result.get("map50"),
        map50_95=result.get("map50_95"),
        mask_map50=result.get("mask_map50"),
        mask_map50_95=result.get("mask_map50_95"),
        sample_count=result.get("sample_count"),
    )


def build_segmentation_evaluation_detail_response(task: object) -> SegmentationEvaluationDetailResponse:
    """把任务记录转换成 segmentation evaluation 详情响应。"""

    summary = build_segmentation_evaluation_summary_response(task)
    return SegmentationEvaluationDetailResponse(
        **summary.model_dump(),
        metadata=dict(task.metadata) if task.metadata else {},
        result=dict(task.result) if task.result else {},
    )
