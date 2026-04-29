"""YOLOX 部署绑定校验接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class YoloXDeploymentBindingRequest:
    """描述一次部署绑定校验请求。

    字段：
    - deployment_instance_id：目标 DeploymentInstance id。
    - model_build_id：待绑定的 ModelBuild id。
    - runtime_profile_id：目标 RuntimeProfile id。
    - task_type：任务类型。
    - required_input_size：要求的输入尺寸。
    - required_device：要求的 device 名称。
    - metadata：附加元数据。
    """

    deployment_instance_id: str
    model_build_id: str
    runtime_profile_id: str
    task_type: str = "detection"
    required_input_size: tuple[int, int] | None = None
    required_device: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXDeploymentBindingResult:
    """描述部署绑定校验结果。

    字段：
    - is_compatible：是否兼容。
    - resolved_backend：最终解析出的 backend。
    - resolved_device：最终解析出的 device。
    - reasons：不兼容或补充说明原因。
    """

    is_compatible: bool
    resolved_backend: str | None = None
    resolved_device: str | None = None
    reasons: tuple[str, ...] = ()


class YoloXDeploymentBinder(Protocol):
    """校验 YOLOX build 能否绑定到指定部署实例。"""

    def validate_binding(self, request: YoloXDeploymentBindingRequest) -> YoloXDeploymentBindingResult:
        """执行部署绑定校验。

        参数：
        - request：部署绑定校验请求。

        返回：
        - 部署绑定校验结果。
        """

        ...