"""deployment 历史事件读取 helper。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.runtime.deployment_events import (
    YoloXDeploymentProcessEvent,
    read_deployment_process_events,
)


@dataclass(frozen=True)
class YoloXDeploymentEventSource:
    """描述 deployment 历史事件读取 helper。

    字段：
    - dataset_storage_root_dir：本地文件存储根目录。
    """

    dataset_storage_root_dir: str

    def list_events(
        self,
        deployment_instance_id: str,
        *,
        after_sequence: int | None = None,
        runtime_mode: str | None = None,
        limit: int | None = None,
    ) -> tuple[YoloXDeploymentProcessEvent, ...]:
        """按 deployment id 读取历史事件列表。

        参数：
        - deployment_instance_id：目标 DeploymentInstance id。
        - after_sequence：可选事件下界；只返回 sequence 更大的事件。
        - runtime_mode：可选运行通道过滤；支持 sync 或 async。
        - limit：可选返回条数上限；为空时返回全部命中的事件。

        返回：
        - tuple[YoloXDeploymentProcessEvent, ...]：按序读取到的 deployment 历史事件。
        """

        return read_deployment_process_events(
            dataset_storage_root_dir=self.dataset_storage_root_dir,
            deployment_instance_id=deployment_instance_id,
            after_sequence=after_sequence,
            runtime_mode=runtime_mode,
            limit=limit,
        )