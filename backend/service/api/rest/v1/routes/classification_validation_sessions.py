"""classification validation session REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.models.classification_validation_session_service import (
    ClassificationValidationSessionCreateRequest,
    ClassificationValidationSessionPredictRequest,
    ClassificationValidationSessionView,
    ClassificationValidationPredictionView,
    LocalClassificationValidationSessionService,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.domain.models.platform_model_support import build_platform_model_type_field_description
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


classification_validation_sessions_router = APIRouter(prefix="/models", tags=["models"])


class ClassificationValidationSessionCreateRequestBody(BaseModel):
    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description=build_platform_model_type_field_description(CLASSIFICATION_TASK_TYPE))
    model_version_id: str = Field(description="验证使用的 ModelVersion id")
    runtime_profile_id: str | None = Field(default=None, description="可选 runtime profile id；当前仅回传")
    runtime_backend: str | None = Field(default=None, description="可选 runtime backend；支持 pytorch、onnxruntime、openvino、tensorrt")
    device_name: str | None = Field(default=None, description="可选 device 名称")
    top_k: int = Field(default=5, ge=1, description="默认返回 top-k 分类结果")
    save_result_image: bool = Field(default=True, description="默认是否输出预览图")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加运行时选项")


class ClassificationValidationCategoryResponse(BaseModel):
    class_id: int = Field(description="类别 id")
    class_name: str | None = Field(default=None, description="类别名")
    probability: float = Field(description="概率值")
    logit: float | None = Field(default=None, description="logit 值")


class ClassificationValidationPredictionSummaryResponse(BaseModel):
    prediction_id: str = Field(description="最近一次预测 id")
    created_at: str = Field(description="最近一次预测创建时间")
    input_uri: str | None = Field(default=None, description="最近一次预测输入 URI")
    input_file_id: str | None = Field(default=None, description="最近一次预测输入 file id")
    category_count: int = Field(description="最近一次预测分类结果数量")
    preview_image_uri: str | None = Field(default=None, description="最近一次预测预览图 URI")
    raw_result_uri: str | None = Field(default=None, description="最近一次预测原始结果 URI")
    latency_ms: float | None = Field(default=None, description="最近一次预测耗时，单位毫秒")


class ClassificationValidationRuntimeTensorSpecResponse(BaseModel):
    name: str = Field(description="张量名称")
    shape: tuple[int, ...] = Field(description="张量形状")
    dtype: str = Field(description="张量数据类型")


class ClassificationValidationRuntimeSessionInfoResponse(BaseModel):
    backend_name: str = Field(description="运行时 backend 名称")
    model_uri: str = Field(description="当前加载的模型 URI")
    device_name: str = Field(description="当前执行 device 名称")
    input_spec: ClassificationValidationRuntimeTensorSpecResponse = Field(description="输入张量规格")
    output_spec: ClassificationValidationRuntimeTensorSpecResponse = Field(description="输出张量规格")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加运行时元数据")


class ClassificationValidationSessionDetailResponse(BaseModel):
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
    runtime_profile_id: str | None = Field(default=None, description="runtime profile id")
    runtime_backend: str = Field(description="运行时 backend 名称")
    device_name: str = Field(description="默认 device 名称")
    runtime_precision: str = Field(description="运行时 precision")
    top_k: int = Field(description="默认 top-k")
    save_result_image: bool = Field(description="默认是否输出预览图")
    input_size: tuple[int, int] = Field(description="推理输入尺寸")
    labels: list[str] = Field(default_factory=list, description="类别列表")
    runtime_artifact_file_id: str = Field(description="当前运行实际加载的模型文件 id")
    runtime_artifact_storage_uri: str = Field(description="当前运行实际加载的模型文件存储 URI")
    runtime_artifact_file_type: str = Field(description="当前运行实际加载的模型文件类型")
    checkpoint_file_id: str | None = Field(default=None, description="来源 checkpoint 文件 id；非训练输出时可为空")
    checkpoint_storage_uri: str | None = Field(default=None, description="来源 checkpoint 文件存储 URI；非训练输出时可为空")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加运行时选项")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="最近更新时间")
    created_by: str | None = Field(default=None, description="创建主体 id")
    last_prediction: ClassificationValidationPredictionSummaryResponse | None = Field(default=None, description="最近一次预测摘要")


class ClassificationValidationSessionPredictRequestBody(BaseModel):
    input_uri: str | None = Field(default=None, description="输入图片 URI 或本地 object key")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id；与 input_uri 二选一")
    top_k: int | None = Field(default=None, ge=1, description="本次预测覆盖的 top-k")
    save_result_image: bool | None = Field(default=None, description="本次预测是否输出预览图")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加运行时选项")


class ClassificationValidationPredictionResponse(BaseModel):
    prediction_id: str = Field(description="预测 id")
    session_id: str = Field(description="所属 validation session id")
    created_at: str = Field(description="预测创建时间")
    input_uri: str | None = Field(default=None, description="输入图片 URI")
    input_file_id: str | None = Field(default=None, description="输入 file id")
    top_k: int = Field(description="本次预测使用的 top-k")
    save_result_image: bool = Field(description="本次预测是否输出预览图")
    categories: list[ClassificationValidationCategoryResponse] = Field(default_factory=list, description="分类结果列表")
    top_category: ClassificationValidationCategoryResponse | None = Field(default=None, description="最高概率类别")
    preview_image_uri: str | None = Field(default=None, description="预览图 URI")
    raw_result_uri: str = Field(description="原始结果 URI")
    latency_ms: float | None = Field(default=None, description="预测耗时，单位毫秒")
    image_width: int = Field(description="输入图片宽度")
    image_height: int = Field(description="输入图片高度")
    labels: list[str] = Field(default_factory=list, description="类别列表")
    runtime_session_info: ClassificationValidationRuntimeSessionInfoResponse = Field(description="runtime 会话信息")


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
    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": body.project_id})
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
    return _build_session_response(session_view)


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
    service = LocalClassificationValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.get_session(session_id)
    if principal.project_ids and session_view.project_id not in principal.project_ids:
        raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": session_view.project_id})
    return _build_session_response(session_view)


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
    service = LocalClassificationValidationSessionService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    session_view = service.get_session(session_id)
    if principal.project_ids and session_view.project_id not in principal.project_ids:
        raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": session_view.project_id})
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
    return _build_prediction_response(prediction_view)


def _build_session_response(session_view: ClassificationValidationSessionView) -> ClassificationValidationSessionDetailResponse:
    return ClassificationValidationSessionDetailResponse(
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
        top_k=session_view.top_k,
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
        last_prediction=_build_prediction_summary_response(session_view.last_prediction),
    )


def _build_prediction_summary_response(summary):
    if summary is None:
        return None
    return ClassificationValidationPredictionSummaryResponse(
        prediction_id=summary.prediction_id,
        created_at=summary.created_at,
        input_uri=summary.input_uri,
        input_file_id=summary.input_file_id,
        category_count=summary.category_count,
        preview_image_uri=summary.preview_image_uri,
        raw_result_uri=summary.raw_result_uri,
        latency_ms=summary.latency_ms,
    )


def _build_prediction_response(prediction_view: ClassificationValidationPredictionView) -> ClassificationValidationPredictionResponse:
    return ClassificationValidationPredictionResponse(
        prediction_id=prediction_view.prediction_id,
        session_id=prediction_view.session_id,
        created_at=prediction_view.created_at,
        input_uri=prediction_view.input_uri,
        input_file_id=prediction_view.input_file_id,
        top_k=prediction_view.top_k,
        save_result_image=prediction_view.save_result_image,
        categories=[
            ClassificationValidationCategoryResponse(
                class_id=c.class_id,
                class_name=c.class_name,
                probability=c.probability,
                logit=c.logit,
            )
            for c in prediction_view.categories
        ],
        top_category=(
            ClassificationValidationCategoryResponse(
                class_id=prediction_view.top_category.class_id,
                class_name=prediction_view.top_category.class_name,
                probability=prediction_view.top_category.probability,
                logit=prediction_view.top_category.logit,
            )
            if prediction_view.top_category is not None
            else None
        ),
        preview_image_uri=prediction_view.preview_image_uri,
        raw_result_uri=prediction_view.raw_result_uri,
        latency_ms=prediction_view.latency_ms,
        image_width=prediction_view.image_width,
        image_height=prediction_view.image_height,
        labels=list(prediction_view.labels),
        runtime_session_info=ClassificationValidationRuntimeSessionInfoResponse(
            backend_name=prediction_view.runtime_session_info.backend_name,
            model_uri=prediction_view.runtime_session_info.model_uri,
            device_name=prediction_view.runtime_session_info.device_name,
            input_spec=ClassificationValidationRuntimeTensorSpecResponse(
                name=prediction_view.runtime_session_info.input_spec.name,
                shape=prediction_view.runtime_session_info.input_spec.shape,
                dtype=prediction_view.runtime_session_info.input_spec.dtype,
            ),
            output_spec=ClassificationValidationRuntimeTensorSpecResponse(
                name=prediction_view.runtime_session_info.output_spec.name,
                shape=prediction_view.runtime_session_info.output_spec.shape,
                dtype=prediction_view.runtime_session_info.output_spec.dtype,
            ),
            metadata=dict(prediction_view.runtime_session_info.metadata),
        ),
    )
