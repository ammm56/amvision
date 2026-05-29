"""classification conversion task REST 路由。"""

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
from backend.service.application.conversions.yolov8_conversion_task_service import SqlAlchemyYoloV8ConversionTaskService, YoloV8ConversionTaskRequest, YOLOV8_CONVERSION_QUEUE_NAME
from backend.service.application.conversions.yolo11_conversion_task_service import SqlAlchemyYolo11ConversionTaskService, Yolo11ConversionTaskRequest, YOLO11_CONVERSION_QUEUE_NAME
from backend.service.application.conversions.yolo26_conversion_task_service import SqlAlchemyYolo26ConversionTaskService, Yolo26ConversionTaskRequest, YOLO26_CONVERSION_QUEUE_NAME
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

classification_conversion_tasks_router = APIRouter(prefix="/models", tags=["models"])

_CONVERSION_SERVICE_MAP = {
    "yolov8": (SqlAlchemyYoloV8ConversionTaskService, YoloV8ConversionTaskRequest, YOLOV8_CONVERSION_QUEUE_NAME),
    "yolo11": (SqlAlchemyYolo11ConversionTaskService, Yolo11ConversionTaskRequest, YOLO11_CONVERSION_QUEUE_NAME),
    "yolo26": (SqlAlchemyYolo26ConversionTaskService, Yolo26ConversionTaskRequest, YOLO26_CONVERSION_QUEUE_NAME),
}

class ClassificationConversionTaskCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id"); model_type: str = Field(description="模型分类")
    model_version_id: str | None = Field(default=None); model_build_id: str | None = Field(default=None)
    target_format: str = Field(description="目标格式"); extra_options: dict[str, object] = Field(default_factory=dict)

class ClassificationConversionTaskSubmissionResponse(BaseModel):
    task_id: str; queue_name: str; queue_task_id: str

@classification_conversion_tasks_router.post("/classification/conversion-tasks", response_model=ClassificationConversionTaskSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
def create_classification_conversion_task(body: ClassificationConversionTaskCreateRequestBody, principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))], sf: Annotated[SessionFactory, Depends(get_session_factory)], qb: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)], ds: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)]) -> ClassificationConversionTaskSubmissionResponse:
    mt = body.model_type.strip().lower()
    entry = _CONVERSION_SERVICE_MAP.get(mt)
    if entry is None:
        raise InvalidRequestError("不支持的模型分类", details={"model_type": mt, "supported": list(_CONVERSION_SERVICE_MAP.keys())})
    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问")
    svc_cls, req_cls, queue_name = entry
    svc = svc_cls(session_factory=sf, queue_backend=qb, dataset_storage=ds)
    r = svc.submit_conversion_task(req_cls(project_id=body.project_id, model_type=mt, task_type="classification", model_version_id=body.model_version_id, model_build_id=body.model_build_id, target_format=body.target_format, extra_options=dict(body.extra_options)), created_by=principal.principal_id)
    return ClassificationConversionTaskSubmissionResponse(task_id=r["task_id"], queue_name=queue_name, queue_task_id=r["queue_task_id"])
