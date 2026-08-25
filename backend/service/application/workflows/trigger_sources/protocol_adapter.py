"""TriggerSource 协议 adapter 接口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.contracts.workflows import TriggerResultContract
from backend.service.application.workflows.trigger_sources.output_delivery import (
    PreparedTriggerResult,
)
from backend.service.application.workflows.trigger_sources.trigger_event_normalizer import (
    RawTriggerEvent,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


@dataclass(frozen=True)
class WorkflowTriggerDispatchResult:
    """adapter 的进程内结果；private handoff receipt 不进入公开 JSON。"""

    trigger_result: TriggerResultContract
    prepared_trigger_result: PreparedTriggerResult | None = None

    @property
    def state(self) -> str:
        """返回公开状态。"""

        return self.trigger_result.state

    @property
    def workflow_run_id(self) -> str | None:
        """返回 WorkflowRun id。"""

        return self.trigger_result.workflow_run_id

    @property
    def metadata(self) -> dict[str, object]:
        """返回公开诊断元数据。"""

        return self.trigger_result.metadata

    @property
    def error_message(self) -> str | None:
        """返回公开错误消息。"""

        return self.trigger_result.error_message

    @property
    def response_payload(self) -> dict[str, object]:
        """返回公开响应 payload。"""

        return self.trigger_result.response_payload

    @property
    def event_id(self) -> str:
        """返回事件 id。"""

        return self.trigger_result.event_id


class WorkflowTriggerEventHandler(Protocol):
    """定义协议 adapter 向触发调用层提交事件的接口。"""

    def handle_trigger_event(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        raw_event: RawTriggerEvent,
    ) -> WorkflowTriggerDispatchResult:
        """处理一条协议事件，并返回公开结果和私有附件生命周期信息。"""

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
