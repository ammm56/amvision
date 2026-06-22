"""classification validation session 请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.domain.models.platform_model_support import (
    build_platform_model_type_field_description,
)


class ClassificationValidationSessionCreateRequestBody(BaseModel):
    """classification validation session 创建请求。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(
        description=build_platform_model_type_field_description(
            CLASSIFICATION_TASK_TYPE
        )
    )
    model_version_id: str = Field(description="验证使用的 ModelVersion id")
    runtime_profile_id: str | None = Field(
        default=None, description="可选 runtime profile id；当前仅回传"
    )
    runtime_backend: str | None = Field(
        default=None,
        description="可选 runtime backend；支持 pytorch、onnxruntime、openvino、tensorrt",
    )
    device_name: str | None = Field(default=None, description="可选 device 名称")
    top_k: int = Field(default=5, ge=1, description="默认返回 top-k 分类结果")
    save_result_image: bool = Field(default=True, description="默认是否输出预览图")
    extra_options: dict[str, object] = Field(
        default_factory=dict, description="附加运行时选项"
    )


class ClassificationValidationSessionPredictRequestBody(BaseModel):
    """classification validation session 预测请求。"""

    input_uri: str | None = Field(
        default=None, description="输入图片 URI 或本地 object key"
    )
    input_file_id: str | None = Field(
        default=None, description="Project 公开文件 id；与 input_uri 二选一"
    )
    top_k: int | None = Field(default=None, ge=1, description="本次预测覆盖的 top-k")
    save_result_image: bool | None = Field(
        default=None, description="本次预测是否输出预览图"
    )
    extra_options: dict[str, object] = Field(
        default_factory=dict, description="附加运行时选项"
    )

