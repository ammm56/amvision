"""segmentation validation session 响应模型和构建函数。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.api.rest.v1.routes.task_validation.services import (
    build_tensor_spec_payload,
)
from backend.service.application.models.validation.segmentation_session_service import (
    SegmentationValidationPredictionView,
    SegmentationValidationSessionView,
)


class SegmentationValidationInstanceResponse(BaseModel):
    """segmentation 实例结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None
    segments: tuple[tuple[tuple[float, float], ...], ...] = ()
    mask_area: float | None = None


class SegmentationValidationPredictionSummaryResponse(BaseModel):
    """最近一次 segmentation 预测摘要。"""

    prediction_id: str
    created_at: str
    input_uri: str | None = None
    input_file_id: str | None = None
    instance_count: int
    preview_image_uri: str | None = None
    raw_result_uri: str | None = None
    latency_ms: float | None = None


class SegmentationValidationTensorSpecResponse(BaseModel):
    """runtime tensor spec 响应。"""

    name: str
    shape: tuple[int, ...]
    dtype: str


class SegmentationValidationRuntimeSessionInfoResponse(BaseModel):
    """segmentation runtime session 信息。"""

    backend_name: str
    model_uri: str
    device_name: str
    input_spec: SegmentationValidationTensorSpecResponse
    output_specs: list[SegmentationValidationTensorSpecResponse] = Field(
        default_factory=list
    )
    metadata: dict[str, object] = Field(default_factory=dict)


class SegmentationValidationSessionDetailResponse(BaseModel):
    """segmentation validation session 详情。"""

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
    mask_threshold: float
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
    last_prediction: SegmentationValidationPredictionSummaryResponse | None = None


class SegmentationValidationPredictionResponse(BaseModel):
    """segmentation validation session 预测响应。"""

    prediction_id: str
    session_id: str
    created_at: str
    input_uri: str | None = None
    input_file_id: str | None = None
    score_threshold: float
    mask_threshold: float
    save_result_image: bool
    instances: list[SegmentationValidationInstanceResponse] = Field(
        default_factory=list
    )
    preview_image_uri: str | None = None
    raw_result_uri: str
    latency_ms: float | None = None
    image_width: int
    image_height: int
    labels: list[str] = Field(default_factory=list)
    runtime_session_info: SegmentationValidationRuntimeSessionInfoResponse


def build_segmentation_validation_session_response(
    session_view: SegmentationValidationSessionView,
) -> SegmentationValidationSessionDetailResponse:
    """把 validation session 视图转换为 REST 响应。"""

    return SegmentationValidationSessionDetailResponse(
        session_id=session_view.session_id,
        project_id=session_view.project_id,
        model_type=session_view.model_type,
        model_id=session_view.model_id,
        model_version_id=session_view.model_version_id,
        model_name=session_view.model_name,
        model_scale=session_view.model_scale,
        source_kind=session_view.source_kind,
        status=session_view.status,
        model_build_id=session_view.model_build_id,
        runtime_profile_id=session_view.runtime_profile_id,
        runtime_backend=session_view.runtime_backend,
        device_name=session_view.device_name,
        runtime_precision=session_view.runtime_precision,
        score_threshold=session_view.score_threshold,
        mask_threshold=session_view.mask_threshold,
        save_result_image=session_view.save_result_image,
        input_size=session_view.input_size,
        labels=list(session_view.labels),
        runtime_artifact_file_id=session_view.runtime_artifact_file_id,
        runtime_artifact_storage_uri=session_view.runtime_artifact_storage_uri,
        runtime_artifact_file_type=session_view.runtime_artifact_file_type,
        checkpoint_file_id=session_view.checkpoint_file_id,
        checkpoint_storage_uri=session_view.checkpoint_storage_uri,
        extra_options=dict(session_view.extra_options),
        created_at=session_view.created_at,
        updated_at=session_view.updated_at,
        created_by=session_view.created_by,
        last_prediction=build_segmentation_validation_prediction_summary_response(
            session_view.last_prediction
        ),
    )


def build_segmentation_validation_prediction_response(
    prediction_view: SegmentationValidationPredictionView,
) -> SegmentationValidationPredictionResponse:
    """把 validation 预测视图转换为 REST 响应。"""

    return SegmentationValidationPredictionResponse(
        prediction_id=prediction_view.prediction_id,
        session_id=prediction_view.session_id,
        created_at=prediction_view.created_at,
        input_uri=prediction_view.input_uri,
        input_file_id=prediction_view.input_file_id,
        score_threshold=prediction_view.score_threshold,
        mask_threshold=prediction_view.mask_threshold,
        save_result_image=prediction_view.save_result_image,
        instances=[
            SegmentationValidationInstanceResponse(
                bbox_xyxy=instance.bbox_xyxy,
                score=instance.score,
                class_id=instance.class_id,
                class_name=instance.class_name,
                segments=instance.segments,
                mask_area=instance.mask_area,
            )
            for instance in prediction_view.instances
        ],
        preview_image_uri=prediction_view.preview_image_uri,
        raw_result_uri=prediction_view.raw_result_uri,
        latency_ms=prediction_view.latency_ms,
        image_width=prediction_view.image_width,
        image_height=prediction_view.image_height,
        labels=list(prediction_view.labels),
        runtime_session_info=SegmentationValidationRuntimeSessionInfoResponse(
            backend_name=prediction_view.runtime_session_info.backend_name,
            model_uri=prediction_view.runtime_session_info.model_uri,
            device_name=prediction_view.runtime_session_info.device_name,
            input_spec=SegmentationValidationTensorSpecResponse(
                **build_tensor_spec_payload(
                    prediction_view.runtime_session_info.input_spec
                )
            ),
            output_specs=[
                SegmentationValidationTensorSpecResponse(
                    **build_tensor_spec_payload(spec)
                )
                for spec in prediction_view.runtime_session_info.output_specs
            ],
            metadata=dict(prediction_view.runtime_session_info.metadata),
        ),
    )


def build_segmentation_validation_prediction_summary_response(
    summary: object | None,
) -> SegmentationValidationPredictionSummaryResponse | None:
    """把预测摘要转换为 REST 响应。"""

    if summary is None:
        return None
    return SegmentationValidationPredictionSummaryResponse(
        prediction_id=summary.prediction_id,
        created_at=summary.created_at,
        input_uri=summary.input_uri,
        input_file_id=summary.input_file_id,
        instance_count=summary.instance_count,
        preview_image_uri=summary.preview_image_uri,
        raw_result_uri=summary.raw_result_uri,
        latency_ms=summary.latency_ms,
    )

