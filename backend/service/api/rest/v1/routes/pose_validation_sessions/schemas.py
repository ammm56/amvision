"""pose validation session 请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.domain.models.model_task_types import POSE_TASK_TYPE
from backend.service.domain.models.platform_model_support import (
    build_platform_model_type_field_description,
)


class PoseValidationSessionCreateRequestBody(BaseModel):
    """pose validation session 创建请求。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(
        description=build_platform_model_type_field_description(POSE_TASK_TYPE)
    )
    model_version_id: str = Field(description="ModelVersion id")
    runtime_profile_id: str | None = Field(default=None)
    runtime_backend: str | None = Field(
        default=None, description="支持 pytorch、onnxruntime、openvino、tensorrt"
    )
    device_name: str | None = Field(default=None)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    keypoint_confidence_threshold: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    save_result_image: bool = Field(default=True)
    extra_options: dict[str, object] = Field(default_factory=dict)


class PoseValidationSessionPredictRequestBody(BaseModel):
    """pose validation session 预测请求。"""

    input_uri: str | None = Field(default=None)
    input_file_id: str | None = Field(default=None)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    keypoint_confidence_threshold: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    save_result_image: bool | None = Field(default=None)
    extra_options: dict[str, object] = Field(default_factory=dict)

