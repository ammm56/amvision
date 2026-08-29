"""segmentation validation session 路由服务。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.segmentation_validation_sessions.responses import (
    SegmentationValidationPredictionResponse,
    SegmentationValidationSessionDetailResponse,
    build_segmentation_validation_prediction_response,
    build_segmentation_validation_session_response,
)
from backend.service.api.rest.v1.routes.segmentation_validation_sessions.schemas import (
    SegmentationValidationSessionCreateRequestBody,
    SegmentationValidationSessionPredictRequestBody,
)
from backend.service.api.rest.v1.routes.task_validation.services import (
    require_validation_project_access,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def create_segmentation_validation_session_response(
    *,
    body: SegmentationValidationSessionCreateRequestBody,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SegmentationValidationSessionDetailResponse:
    """创建 segmentation validation session 并返回响应。"""

    service_cls, create_request_cls, _predict_request_cls = (
        _load_segmentation_validation_service_types()
    )
    require_validation_project_access(
        principal_project_ids=principal.project_ids,
        project_id=body.project_id,
    )
    service = service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.create_session(
        create_request_cls(
            project_id=body.project_id,
            model_type=body.model_type,
            model_version_id=body.model_version_id,
            runtime_profile_id=body.runtime_profile_id,
            runtime_backend=body.runtime_backend,
            device_name=body.device_name,
            score_threshold=body.score_threshold,
            mask_threshold=body.mask_threshold,
            save_result_image=body.save_result_image,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
    )
    return build_segmentation_validation_session_response(session_view)


def get_segmentation_validation_session_response(
    *,
    session_id: str,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SegmentationValidationSessionDetailResponse:
    """读取 segmentation validation session 并返回响应。"""

    service_cls, _create_request_cls, _predict_request_cls = (
        _load_segmentation_validation_service_types()
    )
    service = service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.get_visible_session(
        session_id,
        visible_project_ids=principal.project_ids,
    )
    return build_segmentation_validation_session_response(session_view)


def predict_segmentation_validation_session_response(
    *,
    session_id: str,
    body: SegmentationValidationSessionPredictRequestBody,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SegmentationValidationPredictionResponse:
    """执行 segmentation validation session 单图预测并返回响应。"""

    service_cls, _create_request_cls, predict_request_cls = (
        _load_segmentation_validation_service_types()
    )
    service = service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    service.get_visible_session(
        session_id,
        visible_project_ids=principal.project_ids,
    )
    prediction_view = service.predict(
        session_id,
        predict_request_cls(
            input_uri=body.input_uri,
            input_file_id=body.input_file_id,
            score_threshold=body.score_threshold,
            mask_threshold=body.mask_threshold,
            save_result_image=body.save_result_image,
            extra_options=dict(body.extra_options),
        ),
    )
    return build_segmentation_validation_prediction_response(prediction_view)


def _load_segmentation_validation_service_types() -> tuple[type, type, type]:
    """仅在实际访问 validation API 时加载模型 runtime。"""

    from backend.service.application.models.validation.segmentation_session_service import (
        LocalSegmentationValidationSessionService,
        SegmentationValidationSessionCreateRequest,
        SegmentationValidationSessionPredictRequest,
    )

    return (
        LocalSegmentationValidationSessionService,
        SegmentationValidationSessionCreateRequest,
        SegmentationValidationSessionPredictRequest,
    )
