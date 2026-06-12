"""RF-DETR conversion task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskQueryFilters,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


rfdetr_conversion_tasks_router = APIRouter(prefix="/models", tags=["models"])

RFDETR_CONVERSION_TASK_KIND = "rfdetr-conversion"
RFDETR_CONVERSION_QUEUE_NAME = "rfdetr-conversions"


class RfdetrConversionCreateBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_version_id: str = Field(description="待转换 ModelVersion id")
    checkpoint_object_key: str = Field(description="checkpoint 文件 object key")
    target_format: str = Field(default="onnx", description="目标格式: onnx, onnx-optimized")
    precision: str = Field(default="fp32", description="精度: fp32, fp16")
    model_scale: str = Field(default="nano", description="模型 scale")
    num_classes: int = Field(default=80, ge=1, description="类别数")
    input_size: tuple[int, int] = Field(default=(384, 384), description="输入尺寸")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加选项")
    display_name: str = Field(default="", description="展示名称")


class RfdetrConversionSubmissionResponse(BaseModel):
    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    model_version_id: str


class RfdetrConversionSummaryResponse(BaseModel):
    task_id: str
    display_name: str
    project_id: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    produced_formats: list[str] | None = None
    build_count: int | None = None


class RfdetrConversionDetailResponse(RfdetrConversionSummaryResponse):
    metadata: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)


@rfdetr_conversion_tasks_router.post(
    "/rfdetr/conversion-tasks",
    response_model=RfdetrConversionSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_rfdetr_conversion_task(
    body: RfdetrConversionCreateBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
    qb: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    ds: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> RfdetrConversionSubmissionResponse:
    """创建 RF-DETR 转换任务。"""
    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")

    task_service = SqlAlchemyTaskService(sf)
    task = task_service.create_task(CreateTaskRequest(
        project_id=body.project_id,
        task_kind=RFDETR_CONVERSION_TASK_KIND,
        display_name=body.display_name or f"rfdetr-{body.model_scale}-conversion",
        created_by=principal.principal_id,
        metadata={
            "model_type": "rfdetr",
            "model_version_id": body.model_version_id,
            "model_scale": body.model_scale,
            "num_classes": body.num_classes,
            "input_size": list(body.input_size),
        },
    ))

    queue_task_id = qb.enqueue(
        queue_name=RFDETR_CONVERSION_QUEUE_NAME,
        payload={
            "task_id": task.task_id,
            "project_id": body.project_id,
            "model_version_id": body.model_version_id,
            "checkpoint_object_key": body.checkpoint_object_key,
            "target_format": body.target_format,
            "precision": body.precision,
            "model_scale": body.model_scale,
            "num_classes": body.num_classes,
            "input_size": list(body.input_size),
            "extra_options": dict(body.extra_options),
        },
    )

    return RfdetrConversionSubmissionResponse(
        task_id=task.task_id,
        status="queued",
        queue_name=RFDETR_CONVERSION_QUEUE_NAME,
        queue_task_id=queue_task_id,
        model_version_id=body.model_version_id,
    )


@rfdetr_conversion_tasks_router.get(
    "/rfdetr/conversion-tasks",
    response_model=list[RfdetrConversionSummaryResponse],
)
def list_rfdetr_conversion_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="所属 Project id")],
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RfdetrConversionSummaryResponse]:
    """列出 RF-DETR 转换任务。"""
    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")
    tasks = SqlAlchemyTaskService(sf).list_tasks(TaskQueryFilters(
        project_id=project_id, task_kind=RFDETR_CONVERSION_TASK_KIND, state=state, limit=limit))
    return [_build_summary(t) for t in tasks]


@rfdetr_conversion_tasks_router.get(
    "/rfdetr/conversion-tasks/{task_id}",
    response_model=RfdetrConversionDetailResponse,
)
def get_rfdetr_conversion_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
) -> RfdetrConversionDetailResponse:
    """获取 RF-DETR 转换任务详情。"""
    detail = SqlAlchemyTaskService(sf).get_task(task_id)
    task = detail.task
    if task.task_kind != RFDETR_CONVERSION_TASK_KIND:
        raise ResourceNotFoundError("找不到指定的转换任务")
    summary = _build_summary(task)
    return RfdetrConversionDetailResponse(
        **summary.model_dump(),
        metadata=dict(task.metadata) if task.metadata else {},
        result=dict(task.result) if task.result else {})


@rfdetr_conversion_tasks_router.delete(
    "/rfdetr/conversion-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_rfdetr_conversion_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Response:
    """删除已完成的 RF-DETR 转换任务。"""
    task_svc = SqlAlchemyTaskService(sf)
    detail = task_svc.get_task(task_id)
    if detail.task.task_kind != RFDETR_CONVERSION_TASK_KIND:
        raise ResourceNotFoundError("找不到指定的转换任务")
    if detail.task.state in {"queued", "running"}:
        raise InvalidRequestError("当前转换任务仍在运行中，不能删除")
    task_svc.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _build_summary(task) -> RfdetrConversionSummaryResponse:
    result = dict(task.result) if task.result else {}
    return RfdetrConversionSummaryResponse(
        task_id=task.task_id, display_name=task.display_name, project_id=task.project_id,
        state=task.state, created_at=task.created_at, started_at=task.started_at,
        finished_at=task.finished_at, error_message=task.error_message,
        produced_formats=result.get("produced_formats"),
        build_count=result.get("build_count"))
