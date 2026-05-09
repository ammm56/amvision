"""DeploymentInstance 仓储接口定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.deployments.deployment_instance import DeploymentInstance


class DeploymentInstanceRepository(Protocol):
    """定义 DeploymentInstance 的最小读写接口。"""

    def save_deployment_instance(self, deployment_instance: DeploymentInstance) -> None:
        """保存一个 DeploymentInstance。

        参数：
        - deployment_instance：要保存的 DeploymentInstance。
        """

        ...

    def get_deployment_instance(self, deployment_instance_id: str) -> DeploymentInstance | None:
        """按 id 读取一个 DeploymentInstance。

        参数：
        - deployment_instance_id：DeploymentInstance id。

        返回：
        - 读取到的 DeploymentInstance；不存在时返回 None。
        """

        ...

    def list_deployment_instances(self, project_id: str) -> tuple[DeploymentInstance, ...]:
        """按 Project id 列出 DeploymentInstance。

        参数：
        - project_id：所属 Project id。

        返回：
        - 当前 Project 下的 DeploymentInstance 列表。
        """

        ...

    def delete_deployment_instance(self, deployment_instance_id: str) -> bool:
        """按 id 删除一个 DeploymentInstance。

        参数：
        - deployment_instance_id：DeploymentInstance id。

        返回：
        - bool：存在并已删除时返回 True，不存在时返回 False。
        """

        ...