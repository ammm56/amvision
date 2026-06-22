"""OBB validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.obb_validation_sessions.responses import (
    ObbValidationPredictionResponse,
    ObbValidationSessionDetailResponse,
)
from backend.service.api.rest.v1.routes.obb_validation_sessions.schemas import (
    ObbValidationSessionCreateRequestBody,
    ObbValidationSessionPredictRequestBody,
)
from backend.service.api.rest.v1.routes.obb_validation_sessions.services import (
    create_obb_validation_session_response,
    get_obb_validation_session_response,
    predict_obb_validation_session_response,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


obb_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


@obb_validation_sessions_router.post(
    "/obb/validation-sessions",
    response_model=ObbValidationSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_obb_validation_session(
    body: ObbValidationSessionCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ObbValidationSessionDetailResponse:
    """创建 OBB validation session。"""

    return create_obb_validation_session_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@obb_validation_sessions_router.get(
    "/obb/validation-sessions/{session_id}",
    response_model=ObbValidationSessionDetailResponse,
)
def get_obb_validation_session(
    session_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ObbValidationSessionDetailResponse:
    """读取 OBB validation session。"""

    return get_obb_validation_session_response(
        session_id=session_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@obb_validation_sessions_router.post(
    "/obb/validation-sessions/{session_id}/predict",
    response_model=ObbValidationPredictionResponse,
)
def predict_obb_validation_session(
    session_id: str,
    body: ObbValidationSessionPredictRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ObbValidationPredictionResponse:
    """执行 OBB validation session 单图预测。"""

    return predict_obb_validation_session_response(
        session_id=session_id,
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

