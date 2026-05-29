"""classification training task REST 路由。"""

from __future__ import annotations
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.non_detection_training_management import (
    TrainingTaskDetailResponse,
    TrainingTaskSubmissionResponse,
    TrainingTaskSummaryResponse,
    delete_training_task,
    get_training_task_detail,
    list_training_tasks,
    request_training_control,
    resume_training_task,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.models.yolov8_classification_training_service import (
    SqlAlchemyYoloV8ClassificationTrainingTaskService,
    YoloV8ClassificationTrainingTaskRequest,
)
from backend.service.application.models.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
    Yolo11ClassificationTrainingTaskRequest,
)
from backend.service.application.models.yolo26_classification_training_service import (
    SqlAlchemyYolo26ClassificationTrainingTaskService,
    Yolo26ClassificationTrainingTaskRequest,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

classification_training_tasks_router = APIRouter(prefix="/models", tags=["models"])

_CLS_SERVICE_MAP = {
    "yolov8": (SqlAlchemyYoloV8ClassificationTrainingTaskService, YoloV8ClassificationTrainingTaskRequest),
    "yolo11": (SqlAlchemyYolo11ClassificationTrainingTaskService, Yolo11ClassificationTrainingTaskRequest),
    "yolo26": (SqlAlchemyYolo26ClassificationTrainingTaskService, Yolo26ClassificationTrainingTaskRequest),
}


class ClassificationTrainingTaskCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类；支持 yolov8、yolo11、yolo26")
    dataset_export_id: str | None = Field(default=None, description="DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="导出 manifest key")
    recipe_id: str = Field(default="default", description="训练 recipe id")
    model_scale: str = Field(description="模型 scale")
    output_model_name: str = Field(description="训练后登记的模型名")
    max_epochs: int | None = Field(default=None, ge=1, description="最大训练轮数")
    batch_size: int | None = Field(default=None, ge=1, description="batch size")
    input_size: tuple[int, int] | None = Field(default=None, description="训练输入尺寸")
    precision: str | None = Field(default=None, description="训练 precision")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加训练选项")
    display_name: str = Field(default="", description="可选展示名称")


class ClassificationTrainingTaskSubmissionResponse(BaseModel):
    task_id: str = Field(description="任务 id")
    status: str = Field(description="当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")


@classification_training_tasks_router.post(
    "/classification/training-tasks",
    response_model=ClassificationTrainingTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_classification_training_task(
    body: ClassificationTrainingTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ClassificationTrainingTaskSubmissionResponse:
    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": body.project_id})
    n = body.model_type.strip().lower()
    entry = _CLS_SERVICE_MAP.get(n)
    if entry is None:
        raise InvalidRequestError("当前 classification 训练不支持指定模型分类", details={"model_type": n, "supported": list(_CLS_SERVICE_MAP.keys())})
    svc_cls, req_cls = entry
    svc = svc_cls(session_factory=session_factory, queue_backend=queue_backend, dataset_storage=dataset_storage)
    result = svc.submit_training_task(req_cls(
        project_id=body.project_id, recipe_id=body.recipe_id, model_scale=body.model_scale,
        output_model_name=body.output_model_name, dataset_export_id=body.dataset_export_id,
        dataset_export_manifest_key=body.dataset_export_manifest_key,
        max_epochs=body.max_epochs, batch_size=body.batch_size,
        input_size=body.input_size, precision=body.precision,
        extra_options=dict(body.extra_options), display_name=body.display_name,
    ), created_by=principal.principal_id)
    return ClassificationTrainingTaskSubmissionResponse(
        task_id=result["task_id"], status=result["status"],
        queue_name=result["queue_name"], queue_task_id=result["queue_task_id"],
    )


# ── 训练任务管理端点 ──


@classification_training_tasks_router.get(
    "/classification/training-tasks",
    response_model=list[TrainingTaskSummaryResponse],
)
def list_classification_training_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="所属 Project id")],
    state: Annotated[str | None, Query(description="任务状态")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TrainingTaskSummaryResponse]:
    """列出 classification 训练任务。"""
    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project")
    return list_training_tasks(session_factory=session_factory, project_id=project_id, model_type="classification", state=state, limit=limit)


@classification_training_tasks_router.get(
    "/classification/training-tasks/{task_id}",
    response_model=TrainingTaskDetailResponse,
)
def get_classification_training_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> TrainingTaskDetailResponse:
    """获取 classification 训练任务详情。"""
    return get_training_task_detail(session_factory=session_factory, task_id=task_id)


@classification_training_tasks_router.post(
    "/classification/training-tasks/{task_id}/save",
    response_model=TrainingTaskDetailResponse,
)
def request_classification_training_save(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> TrainingTaskDetailResponse:
    """请求 classification 训练手动保存。"""
    return request_training_control(session_factory=session_factory, dataset_storage=dataset_storage, queue_backend=queue_backend, task_id=task_id, action="save")


@classification_training_tasks_router.post(
    "/classification/training-tasks/{task_id}/pause",
    response_model=TrainingTaskDetailResponse,
)
def request_classification_training_pause(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> TrainingTaskDetailResponse:
    """请求 classification 训练暂停。"""
    return request_training_control(session_factory=session_factory, dataset_storage=dataset_storage, queue_backend=queue_backend, task_id=task_id, action="pause")


@classification_training_tasks_router.post(
    "/classification/training-tasks/{task_id}/terminate",
    response_model=TrainingTaskDetailResponse,
)
def request_classification_training_terminate(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> TrainingTaskDetailResponse:
    """请求 classification 训练终止。"""
    return request_training_control(session_factory=session_factory, dataset_storage=dataset_storage, queue_backend=queue_backend, task_id=task_id, action="terminate")


@classification_training_tasks_router.post(
    "/classification/training-tasks/{task_id}/resume",
    response_model=TrainingTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_classification_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> TrainingTaskSubmissionResponse:
    """继续 paused 的 classification 训练任务。"""
    return resume_training_task(session_factory=session_factory, queue_backend=queue_backend, task_id=task_id)


@classification_training_tasks_router.delete(
    "/classification/training-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_classification_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Response:
    """删除已停止的 classification 训练任务。"""
    delete_training_task(session_factory=session_factory, task_id=task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
