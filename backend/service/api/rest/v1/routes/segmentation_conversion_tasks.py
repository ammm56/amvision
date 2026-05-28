"""segmentation conversion task REST 路由。"""

from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError
from backend.service.application.conversions.yolo_primary_conversion_task_service import SqlAlchemyYoloPrimaryConversionTaskService, YoloPrimaryConversionTaskRequest, YOLO_PRIMARY_CONVERSION_QUEUE_NAME
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

segmentation_conversion_tasks_router = APIRouter(prefix="/models", tags=["models"])
_SUPPORTED_MODELS = ("yolov8", "yolo11", "yolo26")

class SegmentationConversionTaskCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类")
    model_version_id: str | None = Field(default=None)
    model_build_id: str | None = Field(default=None)
    target_format: str = Field(description="目标格式: onnx, onnx-optimized, openvino-ir, tensorrt-engine")
    extra_options: dict[str, object] = Field(default_factory=dict)

class SegmentationConversionTaskSubmissionResponse(BaseModel):
    task_id: str; queue_name: str; queue_task_id: str

@segmentation_conversion_tasks_router.post("/segmentation/conversion-tasks", response_model=SegmentationConversionTaskSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
def create_segmentation_conversion_task(
    body: SegmentationConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    sf: Annotated[SessionFactory, Depends(get_session_factory)],
    qb: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    ds: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> SegmentationConversionTaskSubmissionResponse:
    mt = body.model_type.strip().lower()
    if mt not in _SUPPORTED_MODELS: raise InvalidRequestError("不支持的模型分类", details={"model_type": mt})
    if principal.project_ids and body.project_id not in principal.project_ids: raise PermissionDeniedError("无权访问")
    svc = SqlAlchemyYoloPrimaryConversionTaskService(session_factory=sf, queue_backend=qb, dataset_storage=ds)
    r = svc.submit_conversion_task(YoloPrimaryConversionTaskRequest(project_id=body.project_id, model_type=mt, task_type="segmentation", model_version_id=body.model_version_id, model_build_id=body.model_build_id, target_format=body.target_format, extra_options=dict(body.extra_options)), created_by=principal.principal_id)
    return SegmentationConversionTaskSubmissionResponse(task_id=r["task_id"], queue_name=YOLO_PRIMARY_CONVERSION_QUEUE_NAME, queue_task_id=r["queue_task_id"])
