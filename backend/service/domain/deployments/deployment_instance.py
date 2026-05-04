"""DeploymentInstance 最小领域对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeploymentInstance:
    """描述平台中的最小 DeploymentInstance 对象。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - project_id：所属 Project id。
    - model_id：关联 Model id。
    - model_version_id：当前绑定的 ModelVersion id。
    - model_build_id：当前绑定的 ModelBuild id；未走转换链时可为空。
    - runtime_profile_id：关联的 RuntimeProfile id。
    - runtime_backend：运行时 backend 名称。
    - device_name：部署默认 device 名称。
    - status：部署实例状态。
    - display_name：展示名称。
    - created_at：创建时间。
    - updated_at：最后更新时间。
    - created_by：创建主体 id。
    - metadata：附加元数据。
    """

    deployment_instance_id: str
    project_id: str
    model_id: str
    model_version_id: str
    model_build_id: str | None = None
    runtime_profile_id: str | None = None
    runtime_backend: str = "pytorch"
    device_name: str = "cpu"
    status: str = "active"
    display_name: str = ""
    created_at: str = ""
    updated_at: str = ""
    created_by: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)