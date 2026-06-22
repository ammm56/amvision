"""classification evaluation 响应模型与构建函数。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClassificationEvaluationSubmissionResponse(BaseModel):
    """描述 classification evaluation 提交响应。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_version_id: str
    model_version_id: str


class ClassificationEvaluationSummaryResponse(BaseModel):
    """描述 classification evaluation 摘要响应。"""

    task_id: str
    display_name: str
    project_id: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    top1_accuracy: float | None = None
    top5_accuracy: float | None = None
    sample_count: int | None = None


class ClassificationEvaluationDetailResponse(ClassificationEvaluationSummaryResponse):
    """描述 classification evaluation 详情响应。"""

    metadata: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)


def build_classification_evaluation_summary_response(task: object) -> ClassificationEvaluationSummaryResponse:
    """把任务记录转换成 classification evaluation 摘要响应。"""

    result = dict(task.result) if task.result else {}
    return ClassificationEvaluationSummaryResponse(
        task_id=task.task_id,
        display_name=task.display_name,
        project_id=task.project_id,
        state=task.state,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error_message=task.error_message,
        top1_accuracy=result.get("top1_accuracy"),
        top5_accuracy=result.get("top5_accuracy"),
        sample_count=result.get("sample_count"),
    )


def build_classification_evaluation_detail_response(task: object) -> ClassificationEvaluationDetailResponse:
    """把任务记录转换成 classification evaluation 详情响应。"""

    summary = build_classification_evaluation_summary_response(task)
    return ClassificationEvaluationDetailResponse(
        **summary.model_dump(),
        metadata=dict(task.metadata) if task.metadata else {},
        result=dict(task.result) if task.result else {},
    )
