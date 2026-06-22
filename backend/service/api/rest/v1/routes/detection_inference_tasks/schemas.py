"""detection inference API request schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DetectionInferenceTaskCreateRequestBody(BaseModel):
    """描述 detection 推理任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    deployment_instance_id: str = Field(description="执行推理使用的 DeploymentInstance id")
    model_type: str | None = Field(default=None, description="模型分类；提供时需与 DeploymentInstance 绑定模型一致")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id；与 input_uri、image_base64、input_image 四选一")
    input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
    image_base64: str | None = Field(default=None, description="直接提交的 base64 图片内容")
    input_transport_mode: str = Field(default="storage", description="异步输入传输模式")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="推理阈值")
    save_result_image: bool = Field(default=True, description="是否输出预览图")
    return_preview_image_base64: bool = Field(default=False, description="是否在响应中直接返回预览图 base64")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")
    display_name: str = Field(default="", description="可选展示名称")


class DetectionDirectInferenceRequestBody(BaseModel):
    """描述 detection 同步直返推理请求体。"""

    model_type: str | None = Field(default=None, description="模型分类；提供时需与 DeploymentInstance 绑定模型一致")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id；与 input_uri、image_base64、input_image 四选一")
    input_uri: str | None = Field(default=None, description="输入图片 URI 或 object key")
    image_base64: str | None = Field(default=None, description="直接提交的 base64 图片内容")
    input_transport_mode: str = Field(default="storage", description="同步输入传输模式")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="推理阈值")
    save_result_image: bool = Field(default=True, description="是否输出预览图")
    return_preview_image_base64: bool = Field(default=False, description="是否在响应中直接返回预览图 base64")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加推理选项")
