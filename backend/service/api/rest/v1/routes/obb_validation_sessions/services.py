"""OBB validation session 路由服务。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.obb_validation_sessions.responses import (
    ObbValidationPredictionResponse,
    ObbValidationSessionDetailResponse,
    build_obb_validation_prediction_response,
    build_obb_validation_session_response,
)
from backend.service.api.rest.v1.routes.obb_validation_sessions.schemas import (
    ObbValidationSessionCreateRequestBody,
    ObbValidationSessionPredictRequestBody,
)
from backend.service.api.rest.v1.routes.task_validation.services import (
    require_validation_project_access,
)
from backend.service.application.models.validation.obb_session_service import (
    LocalObbValidationSessionService,
    ObbValidationSessionCreateRequest,
    ObbValidationSessionPredictRequest,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def create_obb_validation_session_response(
    *,
    body: ObbValidationSessionCreateRequestBody,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> ObbValidationSessionDetailResponse:
    """创建 OBB validation session 并返回响应。"""

    require_validation_project_access(
        principal_project_ids=principal.project_ids,
        project_id=body.project_id,
    )
    service = LocalObbValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.create_session(
        ObbValidationSessionCreateRequest(
            project_id=body.project_id,
            model_type=body.model_type,
            model_version_id=body.model_version_id,
            runtime_profile_id=body.runtime_profile_id,
            runtime_backend=body.runtime_backend,
            device_name=body.device_name,
            score_threshold=body.score_threshold,
            save_result_image=body.save_result_image,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
    )
    return build_obb_validation_session_response(session_view)


def get_obb_validation_session_response(
    *,
    session_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> ObbValidationSessionDetailResponse:
    """读取 OBB validation session 并返回响应。"""

    service = LocalObbValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.get_session(session_id)
    require_validation_project_access(
        principal_project_ids=principal.project_ids,
        project_id=session_view.project_id,
    )
    return build_obb_validation_session_response(session_view)


def predict_obb_validation_session_response(
    *,
    session_id: str,
    body: ObbValidationSessionPredictRequestBody,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> ObbValidationPredictionResponse:
    """执行 OBB validation session 单图预测并返回响应。"""

    service = LocalObbValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.get_session(session_id)
    require_validation_project_access(
        principal_project_ids=principal.project_ids,
        project_id=session_view.project_id,
    )
    prediction_view = service.predict(
        session_id,
        ObbValidationSessionPredictRequest(
            input_uri=body.input_uri,
            input_file_id=body.input_file_id,
            score_threshold=body.score_threshold,
            save_result_image=body.save_result_image,
            extra_options=dict(body.extra_options),
        ),
    )
    return build_obb_validation_prediction_response(prediction_view)

