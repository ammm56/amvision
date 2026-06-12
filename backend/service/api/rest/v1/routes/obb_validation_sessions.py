"""obb validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.models.obb_validation_session_service import (
    ObbValidationSessionCreateRequest,
    ObbValidationSessionPredictRequest,
    ObbValidationSessionView,
    ObbValidationPredictionView,
    LocalObbValidationSessionService,
)
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.domain.models.platform_model_support import build_platform_model_type_field_description
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


obb_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


class ObbValidationSessionCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description=build_platform_model_type_field_description(OBB_TASK_TYPE))
    model_version_id: str = Field(description="ModelVersion id")
    runtime_profile_id: str | None = Field(default=None)
    runtime_backend: str | None = Field(default=None, description="支持 pytorch、onnxruntime、openvino、tensorrt")
    device_name: str | None = Field(default=None)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    save_result_image: bool = Field(default=True)
    extra_options: dict[str, object] = Field(default_factory=dict)


class ObbValidationInstanceResponse(BaseModel):
    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None
    angle: float | None = None


class ObbValidationPredictionSummaryResponse(BaseModel):
    prediction_id: str
    created_at: str
    input_uri: str | None = None
    input_file_id: str | None = None
    instance_count: int
    preview_image_uri: str | None = None
    raw_result_uri: str | None = None
    latency_ms: float | None = None


class ObbValidationTensorSpecResponse(BaseModel):
    name: str
    shape: tuple[int, ...]
    dtype: str


class ObbValidationRuntimeSessionInfoResponse(BaseModel):
    backend_name: str
    model_uri: str
    device_name: str
    input_spec: ObbValidationTensorSpecResponse
    output_specs: list[ObbValidationTensorSpecResponse] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class ObbValidationSessionDetailResponse(BaseModel):
    session_id: str
    project_id: str
    model_type: str
    model_id: str
    model_version_id: str
    model_name: str
    model_scale: str
    source_kind: str
    status: str
    model_build_id: str | None = None
    runtime_profile_id: str | None = None
    runtime_backend: str
    device_name: str
    runtime_precision: str
    score_threshold: float
    save_result_image: bool
    input_size: tuple[int, int]
    labels: list[str] = Field(default_factory=list)
    runtime_artifact_file_id: str
    runtime_artifact_storage_uri: str
    runtime_artifact_file_type: str
    checkpoint_file_id: str | None = None
    checkpoint_storage_uri: str | None = None
    extra_options: dict[str, object] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    created_by: str | None = None
    last_prediction: ObbValidationPredictionSummaryResponse | None = None


class ObbValidationSessionPredictRequestBody(BaseModel):
    input_uri: str | None = Field(default=None)
    input_file_id: str | None = Field(default=None)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    save_result_image: bool | None = Field(default=None)
    extra_options: dict[str, object] = Field(default_factory=dict)


class ObbValidationPredictionResponse(BaseModel):
    prediction_id: str
    session_id: str
    created_at: str
    input_uri: str | None = None
    input_file_id: str | None = None
    score_threshold: float
    save_result_image: bool
    instances: list[ObbValidationInstanceResponse] = Field(default_factory=list)
    preview_image_uri: str | None = None
    raw_result_uri: str
    latency_ms: float | None = None
    image_width: int
    image_height: int
    labels: list[str] = Field(default_factory=list)
    runtime_session_info: ObbValidationRuntimeSessionInfoResponse


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
    _check_project(principal, body.project_id)
    service = LocalObbValidationSessionService(session_factory=session_factory, dataset_storage=dataset_storage)
    v = service.create_session(
        ObbValidationSessionCreateRequest(
            project_id=body.project_id, model_type=body.model_type, model_version_id=body.model_version_id,
            runtime_profile_id=body.runtime_profile_id, runtime_backend=body.runtime_backend,
            device_name=body.device_name, score_threshold=body.score_threshold,
            save_result_image=body.save_result_image, extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
    )
    return _build_session_response(v)


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
    service = LocalObbValidationSessionService(session_factory=session_factory, dataset_storage=dataset_storage)
    v = service.get_session(session_id)
    _check_project(principal, v.project_id)
    return _build_session_response(v)


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
    service = LocalObbValidationSessionService(session_factory=session_factory, dataset_storage=dataset_storage)
    v = service.get_session(session_id)
    _check_project(principal, v.project_id)
    pv = service.predict(session_id, ObbValidationSessionPredictRequest(
        input_uri=body.input_uri, input_file_id=body.input_file_id,
        score_threshold=body.score_threshold,
        save_result_image=body.save_result_image, extra_options=dict(body.extra_options),
    ))
    return _build_prediction_response(pv)


def _build_session_response(v: ObbValidationSessionView) -> ObbValidationSessionDetailResponse:
    return ObbValidationSessionDetailResponse(
        session_id=v.session_id, project_id=v.project_id, model_type=v.model_type,
        model_id=v.model_id, model_version_id=v.model_version_id, model_name=v.model_name,
        model_scale=v.model_scale, source_kind=v.source_kind, status=v.status,
        model_build_id=v.model_build_id,
        runtime_profile_id=v.runtime_profile_id, runtime_backend=v.runtime_backend,
        device_name=v.device_name, runtime_precision=v.runtime_precision,
        score_threshold=v.score_threshold,
        save_result_image=v.save_result_image, input_size=v.input_size, labels=list(v.labels),
        runtime_artifact_file_id=v.runtime_artifact_file_id,
        runtime_artifact_storage_uri=v.runtime_artifact_storage_uri,
        runtime_artifact_file_type=v.runtime_artifact_file_type,
        checkpoint_file_id=v.checkpoint_file_id, checkpoint_storage_uri=v.checkpoint_storage_uri,
        extra_options=dict(v.extra_options), created_at=v.created_at, updated_at=v.updated_at,
        created_by=v.created_by, last_prediction=_build_summary_response(v.last_prediction),
    )


def _build_summary_response(s):
    if s is None:
        return None
    return ObbValidationPredictionSummaryResponse(
        prediction_id=s.prediction_id, created_at=s.created_at, input_uri=s.input_uri,
        input_file_id=s.input_file_id, instance_count=s.instance_count,
        preview_image_uri=s.preview_image_uri, raw_result_uri=s.raw_result_uri, latency_ms=s.latency_ms,
    )


def _build_prediction_response(pv: ObbValidationPredictionView) -> ObbValidationPredictionResponse:
    return ObbValidationPredictionResponse(
        prediction_id=pv.prediction_id, session_id=pv.session_id, created_at=pv.created_at,
        input_uri=pv.input_uri, input_file_id=pv.input_file_id,
        score_threshold=pv.score_threshold,
        save_result_image=pv.save_result_image,
        instances=[ObbValidationInstanceResponse(
            bbox_xyxy=i.bbox_xyxy, score=i.score, class_id=i.class_id, class_name=i.class_name,
            angle=i.angle,
        ) for i in pv.instances],
        preview_image_uri=pv.preview_image_uri, raw_result_uri=pv.raw_result_uri,
        latency_ms=pv.latency_ms, image_width=pv.image_width, image_height=pv.image_height,
        labels=list(pv.labels),
        runtime_session_info=ObbValidationRuntimeSessionInfoResponse(
            backend_name=pv.runtime_session_info.backend_name,
            model_uri=pv.runtime_session_info.model_uri,
            device_name=pv.runtime_session_info.device_name,
            input_spec=ObbValidationTensorSpecResponse(
                name=pv.runtime_session_info.input_spec.name,
                shape=pv.runtime_session_info.input_spec.shape,
                dtype=pv.runtime_session_info.input_spec.dtype,
            ),
            output_specs=[ObbValidationTensorSpecResponse(name=s.name, shape=s.shape, dtype=s.dtype) for s in pv.runtime_session_info.output_specs],
            metadata=dict(pv.runtime_session_info.metadata),
        ),
    )


def _check_project(principal: AuthenticatedPrincipal, project_id: str) -> None:
    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": project_id})
