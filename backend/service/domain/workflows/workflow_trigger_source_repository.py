"""workflow trigger source 仓储接口定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


class WorkflowTriggerSourceRepository(Protocol):
    """定义 WorkflowTriggerSource 的最小读写接口。"""

    def save_trigger_source(self, trigger_source: WorkflowTriggerSource) -> None:
        """保存一条 WorkflowTriggerSource。"""

        ...

    def get_trigger_source(
        self, trigger_source_id: str
    ) -> WorkflowTriggerSource | None:
        """按 id 读取一条 WorkflowTriggerSource。"""

        ...

    def list_trigger_sources(
        self, project_id: str
    ) -> tuple[WorkflowTriggerSource, ...]:
        """按 Project id 列出 WorkflowTriggerSource。"""

        ...

    def list_enabled_trigger_sources(self) -> tuple[WorkflowTriggerSource, ...]:
        """列出当前标记为 enabled 的 WorkflowTriggerSource。"""

        ...

    def delete_trigger_source(self, trigger_source_id: str) -> bool:
        """按 id 删除一条 WorkflowTriggerSource。

        参数：
        - trigger_source_id：目标 TriggerSource id。

        返回：
        - bool：存在并已删除时返回 True；不存在时返回 False。
        """

        ...
