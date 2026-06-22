"""pose validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.pose_validation_sessions.responses import (
    PoseValidationPredictionResponse,
    PoseValidationSessionDetailResponse,
)
from backend.service.api.rest.v1.routes.pose_validation_sessions.schemas import (
    PoseValidationSessionCreateRequestBody,
    PoseValidationSessionPredictRequestBody,
)
from backend.service.api.rest.v1.routes.pose_validation_sessions.services import (
    create_pose_validation_session_response,
    get_pose_validation_session_response,
    predict_pose_validation_session_response,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


pose_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


@pose_validation_sessions_router.post(
    "/pose/validation-sessions",
    response_model=PoseValidationSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pose_validation_session(
    body: PoseValidationSessionCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> PoseValidationSessionDetailResponse:
    """创建 pose validation session。"""

    return create_pose_validation_session_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@pose_validation_sessions_router.get(
    "/pose/validation-sessions/{session_id}",
    response_model=PoseValidationSessionDetailResponse,
)
def get_pose_validation_session(
    session_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> PoseValidationSessionDetailResponse:
    """读取 pose validation session。"""

    return get_pose_validation_session_response(
        session_id=session_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@pose_validation_sessions_router.post(
    "/pose/validation-sessions/{session_id}/predict",
    response_model=PoseValidationPredictionResponse,
)
def predict_pose_validation_session(
    session_id: str,
    body: PoseValidationSessionPredictRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> PoseValidationPredictionResponse:
    """执行 pose validation session 单图预测。"""

    return predict_pose_validation_session_response(
        session_id=session_id,
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

