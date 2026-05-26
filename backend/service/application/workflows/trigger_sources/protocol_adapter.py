"""TriggerSource 协议 adapter 接口。"""

from __future__ import annotations

from typing import Protocol

from backend.contracts.workflows import TriggerResultContract
from backend.service.application.workflows.trigger_sources.trigger_event_normalizer import (
    RawTriggerEvent,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


class WorkflowTriggerEventHandler(Protocol):
    """定义协议 adapter 向触发调用层提交事件的接口。"""

    def handle_trigger_event(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        raw_event: RawTriggerEvent,
    ) -> TriggerResultContract:
        """处理一条协议 adapter 收到的原始事件。"""

        ...


class WorkflowTriggerProtocolAdapter(Protocol):
    """定义外部协议 adapter 的生命周期接口。"""

    adapter_kind: str

    def start(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
    ) -> None:
        """启动一个 TriggerSource 对应的协议监听。"""

        ...

    def stop(self, *, trigger_source_id: str) -> None:
        """停止一个 TriggerSource 对应的协议监听。"""

        ...

    def get_health(self, *, trigger_source_id: str) -> dict[str, object]:
        """读取一个 TriggerSource 协议监听的健康状态。"""

        ...
