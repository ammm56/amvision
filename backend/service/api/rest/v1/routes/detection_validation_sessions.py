"""detection validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.models.validation.detection_session_service import (
    DetectionValidationDetection,
    DetectionValidationPredictionSummary,
    DetectionValidationPredictionView,
    DetectionValidationSessionCreateRequest,
    DetectionValidationSessionPredictRequest,
    DetectionValidationSessionView,
    LocalDetectionValidationSessionService,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.platform_model_support import build_platform_model_type_field_description
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


class DetectionValidationSessionCreateRequestBody(BaseModel):
    """描述 detection validation session 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description=build_platform_model_type_field_description(DETECTION_TASK_TYPE))
    model_version_id: str = Field(description="验证使用的 ModelVersion id")
    runtime_profile_id: str | None = Field(default=None, description="可选 runtime profile id；当前仅回传")
    runtime_backend: str | None = Field(default=None, description="可选 runtime backend；支持 pytorch、onnxruntime、openvino、tensorrt")
    device_name: str | None = Field(default=None, description="可选 device 名称；支持 cpu、cuda 或 cuda:<index>")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="默认预测 score threshold")
    save_result_image: bool = Field(default=True, description="默认是否输出预览图")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加运行时选项")


class DetectionValidationPredictionSummaryResponse(BaseModel):
    """描述 validation session 最近一次预测摘要。"""

    prediction_id: str = Field(description="最近一次预测 id")
    created_at: str = Field(description="最近一次预测创建时间")
    input_uri: str | None = Field(default=None, description="最近一次预测输入 URI")
    input_file_id: str | None = Field(default=None, description="最近一次预测输入 file id；输入不是 file_id 时为空")
    detection_count: int = Field(description="最近一次预测 detection 数量")
    preview_image_uri: str | None = Field(default=None, description="最近一次预测预览图 URI")
    raw_result_uri: str | None = Field(default=None, description="最近一次预测原始结果 URI")
    latency_ms: float | None = Field(default=None, description="最近一次预测耗时，单位毫秒")


class DetectionValidationRuntimeTensorSpecResponse(BaseModel):
    """描述 validation runtime 张量规格。"""

    name: str = Field(description="张量名称")
    shape: tuple[int, ...] = Field(description="张量形状")
    dtype: str = Field(description="张量数据类型")


class DetectionValidationRuntimeSessionInfoResponse(BaseModel):
    """描述 validation runtime 固定会话信息。"""

    backend_name: str = Field(description="运行时 backend 名称")
    model_uri: str = Field(description="当前加载的模型 URI")
    device_name: str = Field(description="当前执行 device 名称")
    input_spec: DetectionValidationRuntimeTensorSpecResponse = Field(description="输入张量规格")
    output_spec: DetectionValidationRuntimeTensorSpecResponse = Field(description="输出张量规格")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加运行时元数据")


class DetectionValidationDetectionResponse(BaseModel):
    """描述单条 validation detection 结果。"""

    bbox_xyxy: tuple[float, float, float, float] = Field(description="检测框坐标，格式为 xyxy")
    score: float = Field(description="检测得分")
    class_id: int = Field(description="类别 id")
    class_name: str | None = Field(default=None, description="类别名")


class DetectionValidationSessionDetailResponse(BaseModel):
    """描述 validation session 详情响应。"""

    session_id: str = Field(description="validation session id")
    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类")
    model_id: str = Field(description="关联 Model id")
    model_version_id: str = Field(description="关联 ModelVersion id")
    model_name: str = Field(description="模型名")
    model_scale: str = Field(description="模型 scale")
    source_kind: str = Field(description="ModelVersion 来源类型")
    status: str = Field(description="当前 session 状态")
    model_build_id: str | None = Field(default=None, description="当前运行使用的 ModelBuild id；直接使用 checkpoint 时为空")
    runtime_profile_id: str | None = Field(default=None, description="runtime profile id；当前仅回传")
    runtime_backend: str = Field(description="运行时 backend 名称")
    device_name: str = Field(description="默认 device 名称")
    runtime_precision: str = Field(description="运行时 precision")
    score_threshold: float = Field(description="默认预测 score threshold")
    save_result_image: bool = Field(description="默认是否输出预览图")
    input_size: tuple[int, int] = Field(description="推理输入尺寸")
    labels: list[str] = Field(default_factory=list, description="类别列表")
    runtime_artifact_file_id: str = Field(description="当前运行实际加载的模型文件 id")
    runtime_artifact_storage_uri: str = Field(description="当前运行实际加载的模型文件存储 URI")
    runtime_artifact_file_type: str = Field(description="当前运行实际加载的模型文件类型")
    checkpoint_file_id: str | None = Field(default=None, description="来源 checkpoint 文件 id；非训练输出时可为空")
    checkpoint_storage_uri: str | None = Field(default=None, description="来源 checkpoint 文件存储 URI；非训练输出时可为空")
    labels_storage_uri: str | None = Field(default=None, description="labels 文件存储 URI")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加运行时选项")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="最近更新时间")
    created_by: str | None = Field(default=None, description="创建主体 id")
    last_prediction: DetectionValidationPredictionSummaryResponse | None = Field(default=None, description="最近一次预测摘要")


class DetectionValidationSessionPredictRequestBody(BaseModel):
    """描述 validation session 预测请求体。"""

    input_uri: str | None = Field(default=None, description="输入图片 URI 或本地 object key")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id；与 input_uri 二选一")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="本次预测覆盖的 score threshold")
    save_result_image: bool | None = Field(default=None, description="本次预测是否输出预览图")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加运行时选项")


class DetectionValidationPredictionResponse(BaseModel):
    """描述 validation session 单图预测响应。"""

    prediction_id: str = Field(description="预测 id")
    session_id: str = Field(description="所属 validation session id")
    created_at: str = Field(description="预测创建时间")
    input_uri: str | None = Field(default=None, description="输入图片 URI")
    input_file_id: str | None = Field(default=None, description="输入 file id；输入不是 file_id 时为空")
    score_threshold: float = Field(description="本次预测使用的 score threshold")
    save_result_image: bool = Field(description="本次预测是否输出预览图")
    detections: list[DetectionValidationDetectionResponse] = Field(default_factory=list, description="检测结果列表")
    preview_image_uri: str | None = Field(default=None, description="预览图 URI")
    raw_result_uri: str = Field(description="原始结果 URI")
    latency_ms: float | None = Field(default=None, description="预测耗时，单位毫秒")
    image_width: int = Field(description="输入图片宽度")
    image_height: int = Field(description="输入图片高度")
    labels: list[str] = Field(default_factory=list, description="类别列表")
    runtime_session_info: DetectionValidationRuntimeSessionInfoResponse = Field(description="runtime 会话信息")


@detection_validation_sessions_router.post(
    "/detection/validation-sessions",
    response_model=DetectionValidationSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_detection_validation_session(
    body: DetectionValidationSessionCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionValidationSessionDetailResponse:
    """创建一个用于训练后单图人工验证的 detection validation session。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )

    service = LocalDetectionValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.create_session(
        DetectionValidationSessionCreateRequest(
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
    return _build_detection_validation_session_response(session_view)


@detection_validation_sessions_router.get(
    "/detection/validation-sessions/{session_id}",
    response_model=DetectionValidationSessionDetailResponse,
)
def get_detection_validation_session(
    session_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionValidationSessionDetailResponse:
    """读取指定 detection validation session 详情。"""

    service = LocalDetectionValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.get_session(session_id)
    if principal.project_ids and session_view.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": session_view.project_id},
        )
    return _build_detection_validation_session_response(session_view)


@detection_validation_sessions_router.post(
    "/detection/validation-sessions/{session_id}/predict",
    response_model=DetectionValidationPredictionResponse,
)
def predict_detection_validation_session(
    session_id: str,
    body: DetectionValidationSessionPredictRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionValidationPredictionResponse:
    """对指定 detection validation session 执行一次单图预测。"""

    service = LocalDetectionValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.get_session(session_id)
    if principal.project_ids and session_view.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": session_view.project_id},
        )
    prediction_view = service.predict(
        session_id,
        DetectionValidationSessionPredictRequest(
            input_uri=body.input_uri,
            input_file_id=body.input_file_id,
            score_threshold=body.score_threshold,
            save_result_image=body.save_result_image,
            extra_options=dict(body.extra_options),
        ),
    )
    return _build_detection_validation_prediction_response(prediction_view)


def _build_detection_validation_prediction_summary_response(
    summary: DetectionValidationPredictionSummary | None,
) -> DetectionValidationPredictionSummaryResponse | None:
    """把 validation 预测摘要转换为 REST 响应模型。"""

    if summary is None:
        return None
    return DetectionValidationPredictionSummaryResponse(
        prediction_id=summary.prediction_id,
        created_at=summary.created_at,
        input_uri=summary.input_uri,
        input_file_id=summary.input_file_id,
        detection_count=summary.detection_count,
        preview_image_uri=summary.preview_image_uri,
        raw_result_uri=summary.raw_result_uri,
        latency_ms=summary.latency_ms,
    )


def _build_detection_validation_runtime_tensor_spec_response(
    spec: DetectionRuntimeTensorSpec,
) -> DetectionValidationRuntimeTensorSpecResponse:
    """把 runtime 张量规格转换为 REST 响应模型。"""

    return DetectionValidationRuntimeTensorSpecResponse(name=spec.name, shape=spec.shape, dtype=spec.dtype)


def _build_detection_validation_runtime_session_info_response(
    session_info: DetectionRuntimeSessionInfo,
) -> DetectionValidationRuntimeSessionInfoResponse:
    """把 runtime session info 转换为 REST 响应模型。"""

    return DetectionValidationRuntimeSessionInfoResponse(
        backend_name=session_info.backend_name,
        model_uri=session_info.model_uri,
        device_name=session_info.device_name,
        input_spec=_build_detection_validation_runtime_tensor_spec_response(session_info.input_spec),
        output_spec=_build_detection_validation_runtime_tensor_spec_response(session_info.output_spec),
        metadata=dict(session_info.metadata),
    )


def _build_detection_validation_detection_response(
    detection: DetectionValidationDetection,
) -> DetectionValidationDetectionResponse:
    """把 validation detection 转换为 REST 响应模型。"""

    return DetectionValidationDetectionResponse(
        bbox_xyxy=detection.bbox_xyxy,
        score=detection.score,
        class_id=detection.class_id,
        class_name=detection.class_name,
    )


def _build_detection_validation_session_response(
    session_view: DetectionValidationSessionView,
) -> DetectionValidationSessionDetailResponse:
    """把 validation session 视图转换为 REST 响应模型。"""

    return DetectionValidationSessionDetailResponse(
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
        save_result_image=session_view.save_result_image,
        input_size=session_view.input_size,
        labels=list(session_view.labels),
        runtime_artifact_file_id=session_view.runtime_artifact_file_id,
        runtime_artifact_storage_uri=session_view.runtime_artifact_storage_uri,
        runtime_artifact_file_type=session_view.runtime_artifact_file_type,
        checkpoint_file_id=session_view.checkpoint_file_id,
        checkpoint_storage_uri=session_view.checkpoint_storage_uri,
        labels_storage_uri=session_view.labels_storage_uri,
        extra_options=dict(session_view.extra_options),
        created_at=session_view.created_at,
        updated_at=session_view.updated_at,
        created_by=session_view.created_by,
        last_prediction=_build_detection_validation_prediction_summary_response(session_view.last_prediction),
    )


def _build_detection_validation_prediction_response(
    prediction_view: DetectionValidationPredictionView,
) -> DetectionValidationPredictionResponse:
    """把 validation 预测视图转换为 REST 响应模型。"""

    return DetectionValidationPredictionResponse(
        prediction_id=prediction_view.prediction_id,
        session_id=prediction_view.session_id,
        created_at=prediction_view.created_at,
        input_uri=prediction_view.input_uri,
        input_file_id=prediction_view.input_file_id,
        score_threshold=prediction_view.score_threshold,
        save_result_image=prediction_view.save_result_image,
        detections=[
            _build_detection_validation_detection_response(detection)
            for detection in prediction_view.detections
        ],
        preview_image_uri=prediction_view.preview_image_uri,
        raw_result_uri=prediction_view.raw_result_uri,
        latency_ms=prediction_view.latency_ms,
        image_width=prediction_view.image_width,
        image_height=prediction_view.image_height,
        labels=list(prediction_view.labels),
        runtime_session_info=_build_detection_validation_runtime_session_info_response(
            prediction_view.runtime_session_info
        ),
    )
