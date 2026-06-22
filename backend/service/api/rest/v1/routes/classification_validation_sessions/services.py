"""classification validation session 路由服务。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.classification_validation_sessions.responses import (
    ClassificationValidationPredictionResponse,
    ClassificationValidationSessionDetailResponse,
    build_classification_validation_prediction_response,
    build_classification_validation_session_response,
)
from backend.service.api.rest.v1.routes.classification_validation_sessions.schemas import (
    ClassificationValidationSessionCreateRequestBody,
    ClassificationValidationSessionPredictRequestBody,
)
from backend.service.api.rest.v1.routes.task_validation.services import (
    require_validation_project_access,
)
from backend.service.application.models.validation.classification_session_service import (
    ClassificationValidationSessionCreateRequest,
    ClassificationValidationSessionPredictRequest,
    LocalClassificationValidationSessionService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def create_classification_validation_session_response(
    *,
    body: ClassificationValidationSessionCreateRequestBody,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> ClassificationValidationSessionDetailResponse:
    """创建 classification validation session 并返回响应。"""

    require_validation_project_access(
        principal_project_ids=principal.project_ids,
        project_id=body.project_id,
    )
    service = LocalClassificationValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.create_session(
        ClassificationValidationSessionCreateRequest(
            project_id=body.project_id,
            model_type=body.model_type,
            model_version_id=body.model_version_id,
            runtime_profile_id=body.runtime_profile_id,
            runtime_backend=body.runtime_backend,
            device_name=body.device_name,
            top_k=body.top_k,
            save_result_image=body.save_result_image,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
    )
    return build_classification_validation_session_response(session_view)


def get_classification_validation_session_response(
    *,
    session_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> ClassificationValidationSessionDetailResponse:
    """读取 classification validation session 并返回响应。"""

    service = LocalClassificationValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.get_session(session_id)
    require_validation_project_access(
        principal_project_ids=principal.project_ids,
        project_id=session_view.project_id,
    )
    return build_classification_validation_session_response(session_view)


def predict_classification_validation_session_response(
    *,
    session_id: str,
    body: ClassificationValidationSessionPredictRequestBody,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> ClassificationValidationPredictionResponse:
    """执行 classification validation session 单图预测并返回响应。"""

    service = LocalClassificationValidationSessionService(
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
        ClassificationValidationSessionPredictRequest(
            input_uri=body.input_uri,
            input_file_id=body.input_file_id,
            top_k=body.top_k,
            save_result_image=body.save_result_image,
            extra_options=dict(body.extra_options),
        ),
    )
    return build_classification_validation_prediction_response(prediction_view)

