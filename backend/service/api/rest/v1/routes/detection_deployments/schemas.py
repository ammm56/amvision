"""detection deployment 路由请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.platform_model_support import (
    build_platform_model_type_field_description,
)
from backend.service.api.rest.v1.routes.task_deployments.runtime_configuration_schemas import (
    DeploymentRuntimeConfigurationBody,
)


class DetectionDeploymentInstanceCreateRequestBody(BaseModel):
    """描述 detection DeploymentInstance 创建请求体。"""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(
        description=build_platform_model_type_field_description(DETECTION_TASK_TYPE)
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
