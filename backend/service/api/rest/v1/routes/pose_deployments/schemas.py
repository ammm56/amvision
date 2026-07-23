"""pose deployment API schema。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.service.domain.models.model_task_types import POSE_TASK_TYPE
from backend.service.domain.models.platform_model_support import (
    build_platform_model_type_field_description,
)
from backend.service.api.rest.v1.routes.task_deployments.runtime_configuration_schemas import (
    DeploymentRuntimeConfigurationBody,
)


class PoseDeploymentInstanceCreateRequestBody(BaseModel):
    """描述 pose DeploymentInstance 创建请求体。"""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(
        description=build_platform_model_type_field_description(POSE_TASK_TYPE)
    )
    model_version_id: str | None = Field(
        default=None, description="直接绑定的 ModelVersion id"
    )
    model_build_id: str | None = Field(
        default=None, description="直接绑定的 ModelBuild id"
    )
    runtime_profile_id: str | None = Field(
        default=None, description="可选 RuntimeProfile id"
    )
    runtime_backend: str | None = Field(default=None, description="运行时 backend")
    runtime_precision: str | None = Field(default=None, description="运行时 precision")
    device_name: str | None = Field(default=None, description="默认 device 名称")
    runtime_configuration: DeploymentRuntimeConfigurationBody | None = None
    display_name: str = Field(default="", description="展示名称")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class PoseDeploymentInstanceResponse(BaseModel):
    """描述 pose DeploymentInstance 响应。"""

    deployment_instance_id: str = Field(description="DeploymentInstance id")
    project_id: str = Field(description="所属 Project id")
    model_id: str = Field(description="关联 Model id")
    model_version_id: str | None = Field(
        default=None, description="绑定的 ModelVersion id"
    )
    model_build_id: str | None = Field(default=None, description="绑定的 ModelBuild id")
    model_name: str = Field(description="模型名")
    model_scale: str = Field(description="模型 scale")
    task_type: str = Field(description="任务类型")
    source_kind: str = Field(description="ModelVersion 来源类型")
    display_name: str = Field(description="展示名称")
    status: str = Field(description="实例状态")
    runtime_profile_id: str | None = Field(
        default=None, description="RuntimeProfile id"
    )
    runtime_backend: str = Field(description="运行时 backend")
    device_name: str = Field(description="默认 device 名称")
    runtime_precision: str = Field(description="运行时 precision")
    runtime_execution_mode: str = Field(description="公开展示的运行模式")
    runtime_configuration: DeploymentRuntimeConfigurationBody
    input_size: tuple[int, int] = Field(description="默认输入尺寸")
    labels: tuple[str, ...] = Field(description="类别列表")
    process_status: str | None = Field(default=None, description="进程运行状态")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="最近更新时间")
    created_by: str | None = Field(default=None, description="创建主体 id")
