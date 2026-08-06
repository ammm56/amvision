"""DeploymentInstance 持久化运行状态定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal


DeploymentRuntimeMode = Literal["sync", "async"]
DeploymentRuntimeDesiredState = Literal["stopped", "running"]
DeploymentRuntimeObservedState = Literal[
    "stopped",
    "starting",
    "running",
    "degraded",
    "failed",
]

DEPLOYMENT_RUNTIME_MODES: Final[tuple[DeploymentRuntimeMode, ...]] = (
    "sync",
    "async",
)


@dataclass(frozen=True)
class DeploymentRuntimeState:
    """描述一个 DeploymentInstance 在指定 runtime mode 下的持久化状态。

    字段：
    - deployment_instance_id：所属 DeploymentInstance id。
    - runtime_mode：运行通道，固定为 sync 或 async。
    - desired_state：控制面期望状态。
    - observed_state：runtime controller 最近观测状态。
    - generation：控制命令代数，用于拒绝过期状态回写。
    - controller_owner_id：当前持有控制 lease 的 daemon id。
    - controller_lease_expires_at：控制 lease 到期时间。
    - process_id：最近运行的子进程 pid。
    - heartbeat_at：最近 runtime 心跳时间。
    - restart_count：累计自动恢复次数。
    - consecutive_failure_count：连续恢复失败次数。
    - next_restart_at：退避策略允许的下次恢复时间。
    - last_started_at：最近成功启动时间。
    - last_stopped_at：最近停止时间。
    - last_error_code：最近错误码。
    - last_error_message：最近错误摘要。
    - created_at：记录创建时间。
    - updated_at：记录更新时间。
    """

    deployment_instance_id: str
    runtime_mode: DeploymentRuntimeMode
    desired_state: DeploymentRuntimeDesiredState = "stopped"
    observed_state: DeploymentRuntimeObservedState = "stopped"
    generation: int = 0
    controller_owner_id: str | None = None
    controller_lease_expires_at: str | None = None
    process_id: int | None = None
    heartbeat_at: str | None = None
    restart_count: int = 0
    consecutive_failure_count: int = 0
    next_restart_at: str | None = None
    last_started_at: str | None = None
    last_stopped_at: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: str = ""
    updated_at: str = ""
