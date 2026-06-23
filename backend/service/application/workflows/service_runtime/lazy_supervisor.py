"""workflow service node 按需 deployment supervisor。"""

from __future__ import annotations

from typing import Any


class LazyDeploymentProcessSupervisor:
    """按需创建并启动真实 DeploymentProcessSupervisor。

    字段：
    - dataset_storage_root_dir：deployment 进程读写本地数据集和 buffer 的根目录。
    - runtime_mode：deployment 运行模式，通常是 sync 或 async。
    - settings：DeploymentProcessSupervisor 使用的配置对象。
    - local_buffer_broker_event_channel：可选的 LocalBuffer broker 事件通道。
    """

    def __init__(
        self,
        *,
        dataset_storage_root_dir: str,
        runtime_mode: str,
        settings: object,
        local_buffer_broker_event_channel: object | None = None,
    ) -> None:
        """保存构造参数，直到 workflow 真正调用 deployment 节点时再创建真实实例。"""

        self.dataset_storage_root_dir = dataset_storage_root_dir
        self.runtime_mode = runtime_mode
        self.settings = settings
        self.local_buffer_broker_event_channel = local_buffer_broker_event_channel
        self._supervisor: Any | None = None

    def start(self) -> None:
        """显式启动 supervisor；未被调用时仍保持懒加载。"""

        self._ensure_supervisor()

    def stop(self) -> None:
        """停止已经创建的真实 supervisor；从未使用过时不做任何事。"""

        if self._supervisor is None:
            return
        self._supervisor.stop()

    def __getattr__(self, name: str) -> object:
        """把方法和属性访问转发给按需创建的真实 supervisor。"""

        return getattr(self._ensure_supervisor(), name)

    def _ensure_supervisor(self) -> Any:
        """创建并启动真实 DeploymentProcessSupervisor。"""

        if self._supervisor is not None:
            return self._supervisor
        from backend.service.application.runtime.deployment.deployment_process_supervisor import (
            DeploymentProcessSupervisor,
        )

        supervisor = DeploymentProcessSupervisor(
            dataset_storage_root_dir=self.dataset_storage_root_dir,
            runtime_mode=self.runtime_mode,
            settings=self.settings,
            local_buffer_broker_event_channel=self.local_buffer_broker_event_channel,
        )
        supervisor.start()
        self._supervisor = supervisor
        return supervisor
