"""obb inference 请求 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ObbInferenceTaskCreateRequestBody(BaseModel):
    """描述 obb 异步推理任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    deployment_instance_id: str = Field(description="DeploymentInstance id")
    model_type: str | None = Field(default=None, description="模型分类；提供时需与 DeploymentInstance 绑定模型一致")
    input_file_id: str | None = Field(default=None)
    input_uri: str | None = Field(default=None)
    image_base64: str | None = Field(default=None)
    input_transport_mode: str = Field(default="storage")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    save_result_image: bool = Field(default=False)
    return_preview_image_base64: bool = Field(default=False)
    extra_options: dict[str, object] = Field(default_factory=dict)
    display_name: str = Field(default="")


class ObbDirectInferenceRequestBody(BaseModel):
    """描述 obb 同步直返推理请求体。"""

    model_type: str | None = Field(default=None, description="模型分类；提供时需与 DeploymentInstance 绑定模型一致")
    input_file_id: str | None = Field(default=None)
    input_uri: str | None = Field(default=None)
    image_base64: str | None = Field(default=None)
    input_transport_mode: str = Field(default="storage")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    save_result_image: bool = Field(default=False)
    return_preview_image_base64: bool = Field(default=False)
    extra_options: dict[str, object] = Field(default_factory=dict)
