"""pose training task REST 路由。"""

from __future__ import annotations; from typing import Annotated
from fastapi import APIRouter, Depends, status; from pydantic import BaseModel, Field
from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory; from backend.service.api.deps.queue import get_queue_backend; from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.models.yolo_primary_pose_training_service import SqlAlchemyPoseTrainingTaskService
from backend.service.infrastructure.db.session import SessionFactory; from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

pose_training_tasks_router = APIRouter(prefix="/models", tags=["models"])

class PoseTrainingTaskCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id"); model_type: str = Field(description="模型分类")
    dataset_export_id: str | None = Field(default=None); dataset_export_manifest_key: str | None = Field(default=None)
    recipe_id: str = Field(default="default"); model_scale: str = Field(description="模型 scale")
    output_model_name: str = Field(description="输出模型名")
    max_epochs: int | None = Field(default=None, ge=1); batch_size: int | None = Field(default=None, ge=1)
    input_size: tuple[int, int] | None = Field(default=None); precision: str | None = Field(default=None)
    extra_options: dict[str, object] = Field(default_factory=dict); display_name: str = Field(default="")

class PoseTrainingTaskSubmissionResponse(BaseModel):
    task_id: str; status: str; queue_name: str; queue_task_id: str

@pose_training_tasks_router.post("/pose/training-tasks", response_model=PoseTrainingTaskSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
def create_pose_training_task(body: PoseTrainingTaskCreateRequestBody, principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))], session_factory: Annotated[SessionFactory, Depends(get_session_factory)], queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)], dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)]) -> PoseTrainingTaskSubmissionResponse:
    if principal.project_ids and body.project_id not in principal.project_ids: raise PermissionDeniedError("无权访问该 Project")
    if body.model_type.strip().lower() not in ("yolov8", "yolo11", "yolo26"): raise InvalidRequestError("pose 训练不支持该模型分类")
    svc = SqlAlchemyPoseTrainingTaskService(session_factory=session_factory, queue_backend=queue_backend, dataset_storage=dataset_storage)
    r = svc.submit(project_id=body.project_id, recipe_id=body.recipe_id, model_scale=body.model_scale, output_model_name=body.output_model_name, dataset_export_id=body.dataset_export_id, dataset_export_manifest_key=body.dataset_export_manifest_key, max_epochs=body.max_epochs, batch_size=body.batch_size, input_size=body.input_size, precision=body.precision, extra_options=dict(body.extra_options), display_name=body.display_name, created_by=principal.principal_id)
    return PoseTrainingTaskSubmissionResponse(task_id=r["task_id"], status=r["status"], queue_name=r["queue_name"], queue_task_id=r["queue_task_id"])
