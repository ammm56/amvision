"""detection validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_validation_sessions.responses import (
    DetectionValidationPredictionResponse,
    DetectionValidationSessionDetailResponse,
)
from backend.service.api.rest.v1.routes.detection_validation_sessions.schemas import (
    DetectionValidationSessionCreateRequestBody,
    DetectionValidationSessionPredictRequestBody,
)
from backend.service.api.rest.v1.routes.detection_validation_sessions.services import (
    create_detection_validation_session_response,
    get_detection_validation_session_response,
    predict_detection_validation_session_response,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


detection_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


@detection_validation_sessions_router.post(
    "/detection/validation-sessions",
    response_model=DetectionValidationSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_detection_validation_session(
    body: DetectionValidationSessionCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionValidationSessionDetailResponse:
    """创建一个用于训练后单图人工验证的 detection validation session。"""

    return create_detection_validation_session_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@detection_validation_sessions_router.get(
    "/detection/validation-sessions/{session_id}",
    response_model=DetectionValidationSessionDetailResponse,
)
def get_detection_validation_session(
    session_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionValidationSessionDetailResponse:
    """读取指定 detection validation session 详情。"""

    return get_detection_validation_session_response(
        session_id=session_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@detection_validation_sessions_router.post(
    "/detection/validation-sessions/{session_id}/predict",
    response_model=DetectionValidationPredictionResponse,
)
def predict_detection_validation_session(
    session_id: str,
    body: DetectionValidationSessionPredictRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionValidationPredictionResponse:
    """对指定 detection validation session 执行一次单图预测。"""

    return predict_detection_validation_session_response(
        session_id=session_id,
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

