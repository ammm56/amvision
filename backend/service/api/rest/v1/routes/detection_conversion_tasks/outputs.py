"""detection conversion 结果读取路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_conversion_tasks.responses import (
    DetectionConversionResultResponse,
    build_detection_conversion_result_response,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.services import (
    DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE,
    resolve_detection_conversion_model_type_from_task,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.visibility import (
    require_visible_detection_conversion_task,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_conversion_output_router = APIRouter()


@detection_conversion_output_router.get(
    "/detection/conversion-tasks/{task_id}/result",
    response_model=DetectionConversionResultResponse,
)
def get_detection_conversion_task_result(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionResultResponse:
    """按任务 id 返回当前 detection conversion 结果。"""

    task_detail = require_visible_detection_conversion_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    model_type = resolve_detection_conversion_model_type_from_task(task_detail.task)
    service_cls, _ = DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE[model_type]
    result_snapshot = service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).read_conversion_result(task_id)
    return build_detection_conversion_result_response(task_id, result_snapshot)
