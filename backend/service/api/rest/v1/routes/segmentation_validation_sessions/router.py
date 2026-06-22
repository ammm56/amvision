"""segmentation validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.segmentation_validation_sessions.responses import (
    SegmentationValidationPredictionResponse,
    SegmentationValidationSessionDetailResponse,
)
from backend.service.api.rest.v1.routes.segmentation_validation_sessions.schemas import (
    SegmentationValidationSessionCreateRequestBody,
    SegmentationValidationSessionPredictRequestBody,
)
from backend.service.api.rest.v1.routes.segmentation_validation_sessions.services import (
    create_segmentation_validation_session_response,
    get_segmentation_validation_session_response,
    predict_segmentation_validation_session_response,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


segmentation_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


@segmentation_validation_sessions_router.post(
    "/segmentation/validation-sessions",
    response_model=SegmentationValidationSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_segmentation_validation_session(
    body: SegmentationValidationSessionCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> SegmentationValidationSessionDetailResponse:
    """创建 segmentation validation session。"""

    return create_segmentation_validation_session_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@segmentation_validation_sessions_router.get(
    "/segmentation/validation-sessions/{session_id}",
    response_model=SegmentationValidationSessionDetailResponse,
)
def get_segmentation_validation_session(
    session_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> SegmentationValidationSessionDetailResponse:
    """读取 segmentation validation session。"""

    return get_segmentation_validation_session_response(
        session_id=session_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@segmentation_validation_sessions_router.post(
    "/segmentation/validation-sessions/{session_id}/predict",
    response_model=SegmentationValidationPredictionResponse,
)
def predict_segmentation_validation_session(
    session_id: str,
    body: SegmentationValidationSessionPredictRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> SegmentationValidationPredictionResponse:
    """执行 segmentation validation session 单图预测。"""

    return predict_segmentation_validation_session_response(
        session_id=session_id,
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

