"""Pose 评估任务 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.models.pose_evaluation_task_service import (
    POSE_EVALUATION_QUEUE_NAME,
    POSE_EVALUATION_TASK_KIND,
    SqlAlchemyPoseEvaluationTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory

pose_evaluation_tasks_router = APIRouter(prefix="/models/pose", tags=["pose"])


class PoseEvaluationTaskCreateBody(BaseModel):
    """Pose 评估任务创建请求。"""
    dataset_export_id: str = Field(..., description="数据集导出 ID")
    model_version_id: str = Field(..., description="模型版本 ID")
    score_threshold: float = Field(default=0.01, ge=0.0, le=1.0, description="置信度阈值")
    output_prefix: str | None = Field(default=None, description="输出前缀（可选）")


class PoseEvaluationTaskSubmitResponse(BaseModel):
    """Pose 评估任务提交响应。"""
    task_id: str
    status: str
    queue_name: str
    queue_task_id: str


@pose_evaluation_tasks_router.post(
    "/evaluation-tasks",
    response_model=PoseEvaluationTaskSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_pose_evaluation_task(
    body: PoseEvaluationTaskCreateBody,
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[object, Depends(get_queue_backend)],
    dataset_storage: Annotated[object, Depends(get_dataset_storage)],
    _: bool = Depends(require_scopes("tasks:write")),
):
    """创建 Pose 评估任务。"""
    from backend.queue import LocalFileQueueBackend

    queue_backend: LocalFileQueueBackend
    task_service = SqlAlchemyPoseEvaluationTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )

    # 创建任务记录
    from backend.service.application.tasks.task_service import SqlAlchemyTaskService, CreateTaskRequest

    task_svc = SqlAlchemyTaskService(session_factory)
    task_id = task_svc.create_task(CreateTaskRequest(
        task_kind=POSE_EVALUATION_TASK_KIND,
        status="queued",
        task_spec={
            "dataset_export_id": body.dataset_export_id,
            "model_version_id": body.model_version_id,
            "score_threshold": body.score_threshold,
            "output_prefix": body.output_prefix or f"task-runs/pose-evaluation",
        },
    ))

    # 入队
    queue_task_id = queue_backend.enqueue(
        queue_name=POSE_EVALUATION_QUEUE_NAME,
        payload={"task_id": task_id},
    )

    # 记录事件
    task_svc.append_task_event(task_id, "status", "queued", "Pose 评估任务已入队")

    return PoseEvaluationTaskSubmitResponse(
        task_id=task_id,
        status="queued",
        queue_name=POSE_EVALUATION_QUEUE_NAME,
        queue_task_id=queue_task_id,
    )
