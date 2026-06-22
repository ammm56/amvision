"""detection conversion 路由请求和响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.platform_model_support import build_platform_model_type_field_description


DetectionConversionTargetLiteral = Literal[
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
    "rknn",
]


class DetectionConversionTaskCreateRequestBody(BaseModel):
    """描述 detection conversion 任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description=build_platform_model_type_field_description(DETECTION_TASK_TYPE))
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加转换选项")
    display_name: str = Field(default="", description="可选任务展示名称")


class DetectionConversionTaskSubmissionResponse(BaseModel):
    """描述 detection conversion 任务创建响应。"""

    task_id: str = Field(description="转换任务 id")
    status: str = Field(description="转换任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    model_type: str = Field(description="模型分类")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[DetectionConversionTargetLiteral] = Field(description="固化后的目标格式列表")
