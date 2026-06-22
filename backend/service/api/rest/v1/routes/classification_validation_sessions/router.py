"""classification validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.classification_validation_sessions.responses import (
    ClassificationValidationPredictionResponse,
    ClassificationValidationSessionDetailResponse,
)
from backend.service.api.rest.v1.routes.classification_validation_sessions.schemas import (
    ClassificationValidationSessionCreateRequestBody,
    ClassificationValidationSessionPredictRequestBody,
)
from backend.service.api.rest.v1.routes.classification_validation_sessions.services import (
    create_classification_validation_session_response,
    get_classification_validation_session_response,
    predict_classification_validation_session_response,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


classification_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


@classification_validation_sessions_router.post(
    "/classification/validation-sessions",
    response_model=ClassificationValidationSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_classification_validation_session(
    body: ClassificationValidationSessionCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ClassificationValidationSessionDetailResponse:
    """创建 classification validation session。"""

    return create_classification_validation_session_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@classification_validation_sessions_router.get(
    "/classification/validation-sessions/{session_id}",
    response_model=ClassificationValidationSessionDetailResponse,
)
def get_classification_validation_session(
    session_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ClassificationValidationSessionDetailResponse:
    """读取 classification validation session。"""

    return get_classification_validation_session_response(
        session_id=session_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@classification_validation_sessions_router.post(
    "/classification/validation-sessions/{session_id}/predict",
    response_model=ClassificationValidationPredictionResponse,
)
def predict_classification_validation_session(
    session_id: str,
    body: ClassificationValidationSessionPredictRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ClassificationValidationPredictionResponse:
    """执行 classification validation session 单图预测。"""

    return predict_classification_validation_session_response(
        session_id=session_id,
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

