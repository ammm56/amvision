"""Deployment runtime state 仓储接口。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.deployments.deployment_runtime_state import (
    DeploymentRuntimeMode,
    DeploymentRuntimeState,
)


class DeploymentRuntimeStateRepository(Protocol):
    """定义 deployment runtime state 的持久化边界。"""

    def save_deployment_runtime_state(self, state: DeploymentRuntimeState) -> None:
        """新增或更新一条 runtime state。"""

        ...

    def try_save_deployment_runtime_state(
        self,
        state: DeploymentRuntimeState,
        *,
        expected_generation: int,
    ) -> bool:
        """仅在 generation 未变化时原子更新 runtime state。"""

        ...

    def get_deployment_runtime_state(
        self,
        deployment_instance_id: str,
        runtime_mode: DeploymentRuntimeMode,
    ) -> DeploymentRuntimeState | None:
        """按 DeploymentInstance 和 runtime mode 读取状态。"""

        ...

    def list_deployment_runtime_states(
        self,
        *,
        desired_state: str | None = None,
    ) -> tuple[DeploymentRuntimeState, ...]:
        """列出全部或指定期望状态的 runtime state。"""

        ...

    def delete_deployment_runtime_states(self, deployment_instance_id: str) -> int:
        """删除指定 DeploymentInstance 的全部 runtime state。"""

        ...

    def try_claim_deployment_runtime_state(
        self,
        *,
        deployment_instance_id: str,
        runtime_mode: DeploymentRuntimeMode,
        expected_generation: int,
        owner_id: str,
        now: str,
        lease_expires_at: str,
    ) -> bool:
        """使用 generation 和 lease 原子领取 runtime state。"""

        ...
