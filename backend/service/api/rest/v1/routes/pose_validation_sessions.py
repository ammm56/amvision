"""pose validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.models.pose_validation_session_service import (
    PoseValidationSessionCreateRequest,
    PoseValidationSessionPredictRequest,
    PoseValidationSessionView,
    PoseValidationPredictionView,
    LocalPoseValidationSessionService,
)
from backend.service.application.runtime.pose_runtime_contracts import PosePredictionKeypoint
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


pose_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


class PoseValidationSessionCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类；支持 yolov8、yolo11、yolo26")
    model_version_id: str = Field(description="ModelVersion id")
    runtime_profile_id: str | None = Field(default=None)
    runtime_backend: str | None = Field(default=None, description="支持 pytorch、onnxruntime、openvino、tensorrt")
    device_name: str | None = Field(default=None)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    keypoint_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    save_result_image: bool = Field(default=True)
    extra_options: dict[str, object] = Field(default_factory=dict)


class PoseValidationKeypointResponse(BaseModel):
    x: float
    y: float
    confidence: float | None = None


class PoseValidationInstanceResponse(BaseModel):
    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None
    keypoints: tuple[PoseValidationKeypointResponse, ...] = ()
    kpt_shape: tuple[int, int] = (17, 3)


class PoseValidationPredictionSummaryResponse(BaseModel):
    prediction_id: str
    created_at: str
    input_uri: str | None = None
    input_file_id: str | None = None
    instance_count: int
    preview_image_uri: str | None = None
    raw_result_uri: str | None = None
    latency_ms: float | None = None


class PoseValidationTensorSpecResponse(BaseModel):
    name: str
    shape: tuple[int, ...]
    dtype: str


class PoseValidationRuntimeSessionInfoResponse(BaseModel):
    backend_name: str
    model_uri: str
    device_name: str
    input_spec: PoseValidationTensorSpecResponse
    output_specs: list[PoseValidationTensorSpecResponse] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class PoseValidationSessionDetailResponse(BaseModel):
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
    keypoint_confidence_threshold: float
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
    last_prediction: PoseValidationPredictionSummaryResponse | None = None


class PoseValidationSessionPredictRequestBody(BaseModel):
    input_uri: str | None = Field(default=None)
    input_file_id: str | None = Field(default=None)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    keypoint_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    save_result_image: bool | None = Field(default=None)
    extra_options: dict[str, object] = Field(default_factory=dict)


class PoseValidationPredictionResponse(BaseModel):
    prediction_id: str
    session_id: str
    created_at: str
    input_uri: str | None = None
    input_file_id: str | None = None
    score_threshold: float
    keypoint_confidence_threshold: float
    save_result_image: bool
    instances: list[PoseValidationInstanceResponse] = Field(default_factory=list)
    preview_image_uri: str | None = None
    raw_result_uri: str
    latency_ms: float | None = None
    image_width: int
    image_height: int
    labels: list[str] = Field(default_factory=list)
    runtime_session_info: PoseValidationRuntimeSessionInfoResponse


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
    _check_project(principal, body.project_id)
    service = LocalPoseValidationSessionService(session_factory=session_factory, dataset_storage=dataset_storage)
    v = service.create_session(
        PoseValidationSessionCreateRequest(
            project_id=body.project_id, model_type=body.model_type, model_version_id=body.model_version_id,
            runtime_profile_id=body.runtime_profile_id, runtime_backend=body.runtime_backend,
            device_name=body.device_name, score_threshold=body.score_threshold,
            keypoint_confidence_threshold=body.keypoint_confidence_threshold,
            save_result_image=body.save_result_image, extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
    )
    return _build_session_response(v)


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
    service = LocalPoseValidationSessionService(session_factory=session_factory, dataset_storage=dataset_storage)
    v = service.get_session(session_id)
    _check_project(principal, v.project_id)
    return _build_session_response(v)


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
    service = LocalPoseValidationSessionService(session_factory=session_factory, dataset_storage=dataset_storage)
    v = service.get_session(session_id)
    _check_project(principal, v.project_id)
    pv = service.predict(session_id, PoseValidationSessionPredictRequest(
        input_uri=body.input_uri, input_file_id=body.input_file_id,
        score_threshold=body.score_threshold,
        keypoint_confidence_threshold=body.keypoint_confidence_threshold,
        save_result_image=body.save_result_image, extra_options=dict(body.extra_options),
    ))
    return _build_prediction_response(pv)


def _build_session_response(v: PoseValidationSessionView) -> PoseValidationSessionDetailResponse:
    return PoseValidationSessionDetailResponse(
        session_id=v.session_id, project_id=v.project_id, model_type=v.model_type,
        model_id=v.model_id, model_version_id=v.model_version_id, model_name=v.model_name,
        model_scale=v.model_scale, source_kind=v.source_kind, status=v.status,
        model_build_id=v.model_build_id,
        runtime_profile_id=v.runtime_profile_id, runtime_backend=v.runtime_backend,
        device_name=v.device_name, runtime_precision=v.runtime_precision,
        score_threshold=v.score_threshold,
        keypoint_confidence_threshold=v.keypoint_confidence_threshold,
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
    return PoseValidationPredictionSummaryResponse(
        prediction_id=s.prediction_id, created_at=s.created_at, input_uri=s.input_uri,
        input_file_id=s.input_file_id, instance_count=s.instance_count,
        preview_image_uri=s.preview_image_uri, raw_result_uri=s.raw_result_uri, latency_ms=s.latency_ms,
    )


def _build_prediction_response(pv: PoseValidationPredictionView) -> PoseValidationPredictionResponse:
    return PoseValidationPredictionResponse(
        prediction_id=pv.prediction_id, session_id=pv.session_id, created_at=pv.created_at,
        input_uri=pv.input_uri, input_file_id=pv.input_file_id,
        score_threshold=pv.score_threshold,
        keypoint_confidence_threshold=pv.keypoint_confidence_threshold,
        save_result_image=pv.save_result_image,
        instances=[PoseValidationInstanceResponse(
            bbox_xyxy=i.bbox_xyxy, score=i.score, class_id=i.class_id, class_name=i.class_name,
            keypoints=tuple(PoseValidationKeypointResponse(x=kp.x, y=kp.y, confidence=kp.confidence) for kp in i.keypoints),
            kpt_shape=i.kpt_shape,
        ) for i in pv.instances],
        preview_image_uri=pv.preview_image_uri, raw_result_uri=pv.raw_result_uri,
        latency_ms=pv.latency_ms, image_width=pv.image_width, image_height=pv.image_height,
        labels=list(pv.labels),
        runtime_session_info=PoseValidationRuntimeSessionInfoResponse(
            backend_name=pv.runtime_session_info.backend_name,
            model_uri=pv.runtime_session_info.model_uri,
            device_name=pv.runtime_session_info.device_name,
            input_spec=PoseValidationTensorSpecResponse(
                name=pv.runtime_session_info.input_spec.name,
                shape=pv.runtime_session_info.input_spec.shape,
                dtype=pv.runtime_session_info.input_spec.dtype,
            ),
            output_specs=[PoseValidationTensorSpecResponse(name=s.name, shape=s.shape, dtype=s.dtype) for s in pv.runtime_session_info.output_specs],
            metadata=dict(pv.runtime_session_info.metadata),
        ),
    )


def _check_project(principal: AuthenticatedPrincipal, project_id: str) -> None:
    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError("无权访问该 Project", details={"project_id": project_id})
