"""classification validation session 响应模型和构建函数。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.api.rest.v1.routes.task_validation.services import (
    build_tensor_spec_payload,
)
from backend.service.application.models.validation.classification_session_service import (
    ClassificationValidationPredictionView,
    ClassificationValidationSessionView,
)


class ClassificationValidationCategoryResponse(BaseModel):
    """分类结果条目。"""

    class_id: int = Field(description="类别 id")
    class_name: str | None = Field(default=None, description="类别名")
    probability: float = Field(description="概率值")
    logit: float | None = Field(default=None, description="logit 值")


class ClassificationValidationPredictionSummaryResponse(BaseModel):
    """最近一次分类预测摘要。"""

    prediction_id: str = Field(description="最近一次预测 id")
    created_at: str = Field(description="最近一次预测创建时间")
    input_uri: str | None = Field(default=None, description="最近一次预测输入 URI")
    input_file_id: str | None = Field(
        default=None, description="最近一次预测输入 file id"
    )
    category_count: int = Field(description="最近一次预测分类结果数量")
    preview_image_uri: str | None = Field(
        default=None, description="最近一次预测预览图 URI"
    )
    raw_result_uri: str | None = Field(
        default=None, description="最近一次预测原始结果 URI"
    )
    latency_ms: float | None = Field(
        default=None, description="最近一次预测耗时，单位毫秒"
    )


class ClassificationValidationRuntimeTensorSpecResponse(BaseModel):
    """runtime tensor spec 响应。"""

    name: str = Field(description="张量名称")
    shape: tuple[int, ...] = Field(description="张量形状")
    dtype: str = Field(description="张量数据类型")


class ClassificationValidationRuntimeSessionInfoResponse(BaseModel):
    """classification runtime session 信息。"""

    backend_name: str = Field(description="运行时 backend 名称")
    model_uri: str = Field(description="当前加载的模型 URI")
    device_name: str = Field(description="当前执行 device 名称")
    input_spec: ClassificationValidationRuntimeTensorSpecResponse = Field(
        description="输入张量规格"
    )
    output_spec: ClassificationValidationRuntimeTensorSpecResponse = Field(
        description="输出张量规格"
    )
    metadata: dict[str, object] = Field(default_factory=dict, description="附加运行时元数据")


class ClassificationValidationSessionDetailResponse(BaseModel):
    """classification validation session 详情。"""

    session_id: str = Field(description="validation session id")
    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类")
    model_id: str = Field(description="关联 Model id")
    model_version_id: str = Field(description="关联 ModelVersion id")
    model_name: str = Field(description="模型名")
    model_scale: str = Field(description="模型 scale")
    source_kind: str = Field(description="ModelVersion 来源类型")
    status: str = Field(description="当前 session 状态")
    model_build_id: str | None = Field(
        default=None, description="当前运行使用的 ModelBuild id；直接使用 checkpoint 时为空"
    )
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
    checkpoint_file_id: str | None = Field(
        default=None, description="来源 checkpoint 文件 id；非训练输出时可为空"
    )
    checkpoint_storage_uri: str | None = Field(
        default=None, description="来源 checkpoint 文件存储 URI；非训练输出时可为空"
    )
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加运行时选项")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="最近更新时间")
    created_by: str | None = Field(default=None, description="创建主体 id")
    last_prediction: ClassificationValidationPredictionSummaryResponse | None = Field(
        default=None, description="最近一次预测摘要"
    )


class ClassificationValidationPredictionResponse(BaseModel):
    """classification validation session 预测响应。"""

    prediction_id: str = Field(description="预测 id")
    session_id: str = Field(description="所属 validation session id")
    created_at: str = Field(description="预测创建时间")
    input_uri: str | None = Field(default=None, description="输入图片 URI")
    input_file_id: str | None = Field(default=None, description="输入 file id")
    top_k: int = Field(description="本次预测使用的 top-k")
    save_result_image: bool = Field(description="本次预测是否输出预览图")
    categories: list[ClassificationValidationCategoryResponse] = Field(
        default_factory=list, description="分类结果列表"
    )
    top_category: ClassificationValidationCategoryResponse | None = Field(
        default=None, description="最高概率类别"
    )
    preview_image_uri: str | None = Field(default=None, description="预览图 URI")
    raw_result_uri: str = Field(description="原始结果 URI")
    latency_ms: float | None = Field(default=None, description="预测耗时，单位毫秒")
    image_width: int = Field(description="输入图片宽度")
    image_height: int = Field(description="输入图片高度")
    labels: list[str] = Field(default_factory=list, description="类别列表")
    runtime_session_info: ClassificationValidationRuntimeSessionInfoResponse = Field(
        description="runtime 会话信息"
    )


def build_classification_validation_session_response(
    session_view: ClassificationValidationSessionView,
) -> ClassificationValidationSessionDetailResponse:
    """把 validation session 视图转换为 REST 响应。"""

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
        last_prediction=build_classification_validation_prediction_summary_response(
            session_view.last_prediction
        ),
    )


def build_classification_validation_prediction_response(
    prediction_view: ClassificationValidationPredictionView,
) -> ClassificationValidationPredictionResponse:
    """把 validation 预测视图转换为 REST 响应。"""

    return ClassificationValidationPredictionResponse(
        prediction_id=prediction_view.prediction_id,
        session_id=prediction_view.session_id,
        created_at=prediction_view.created_at,
        input_uri=prediction_view.input_uri,
        input_file_id=prediction_view.input_file_id,
        top_k=prediction_view.top_k,
        save_result_image=prediction_view.save_result_image,
        categories=[
            build_classification_validation_category_response(category)
            for category in prediction_view.categories
        ],
        top_category=(
            build_classification_validation_category_response(
                prediction_view.top_category
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
                **build_tensor_spec_payload(
                    prediction_view.runtime_session_info.input_spec
                )
            ),
            output_spec=ClassificationValidationRuntimeTensorSpecResponse(
                **build_tensor_spec_payload(
                    prediction_view.runtime_session_info.output_spec
                )
            ),
            metadata=dict(prediction_view.runtime_session_info.metadata),
        ),
    )


def build_classification_validation_prediction_summary_response(
    summary: object | None,
) -> ClassificationValidationPredictionSummaryResponse | None:
    """把预测摘要转换为 REST 响应。"""

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


def build_classification_validation_category_response(
    category: object,
) -> ClassificationValidationCategoryResponse:
    """把分类条目转换为 REST 响应。"""

    return ClassificationValidationCategoryResponse(
        class_id=category.class_id,
        class_name=category.class_name,
        probability=category.probability,
        logit=category.logit,
    )

