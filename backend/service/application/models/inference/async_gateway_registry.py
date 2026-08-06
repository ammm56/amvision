"""Async inference gateway registry 的稳定生命周期协议。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AsyncInferenceGatewayRegistry(Protocol):
    """定义 deployment 控制面依赖的最小 dispatcher registry 能力。"""

    def ensure_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        """确保指定 deployment 的 dispatcher 已启动。"""

    def stop_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        """停止指定 deployment 的 dispatcher。"""
