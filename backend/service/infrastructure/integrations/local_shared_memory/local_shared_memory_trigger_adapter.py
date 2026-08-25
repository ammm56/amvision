"""把 TriggerSource 生命周期接入全局 Workflow Trigger mailbox。"""

from __future__ import annotations

from threading import RLock

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.trigger_sources.local_shared_mailbox_supervisor import (
    WorkflowTriggerMailboxSupervisor,
)
from backend.service.application.workflows.trigger_sources.protocol_adapter import (
    WorkflowTriggerEventHandler,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


class LocalSharedMemoryTriggerAdapter:
    """登记本机共享内存 TriggerSource；数据面由全局 mailbox 处理。"""

    adapter_kind = "local-shared-memory"

    def __init__(
        self,
        *,
        mailbox_supervisor: WorkflowTriggerMailboxSupervisor,
    ) -> None:
        """初始化 adapter，并复用进程级唯一 mailbox supervisor。"""

        self.mailbox_supervisor = mailbox_supervisor
        self._route_generations: dict[str, int] = {}
        self._lock = RLock()

    def start(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
    ) -> None:
        """登记稳定路由；mailbox 自己完成 Runtime admission 和结果回写。"""

        del event_handler
        if trigger_source.trigger_kind != self.adapter_kind:
            raise InvalidRequestError(
                "LocalSharedMemoryTriggerAdapter 只接受 local-shared-memory"
            )
        route = self.mailbox_supervisor.register_trigger_source(trigger_source)
        with self._lock:
            self._route_generations[trigger_source.trigger_source_id] = (
                route.route_generation
            )

    def stop(self, *, trigger_source_id: str) -> None:
        """停止新请求路由；已进入 mailbox 的请求继续按 identity 收尾。"""

        self.mailbox_supervisor.unregister_trigger_source(trigger_source_id)
        with self._lock:
            self._route_generations.pop(trigger_source_id, None)

    def get_health(self, *, trigger_source_id: str) -> dict[str, object]:
        """返回 source 路由和全局容量摘要，不暴露图片或业务内容。"""

        with self._lock:
            route_generation = self._route_generations.get(trigger_source_id)
        status = self.mailbox_supervisor.build_status()
        completed_request_count = int(status["completed_request_count"])
        failed_request_count = int(status["failed_request_count"])
        return {
            "adapter_kind": self.adapter_kind,
            "running": route_generation is not None and status["running"],
            "route_generation": route_generation,
            "pending_request_count": status["pending_request_count"],
            "active_task_count": status["active_task_count"],
            "request_count": completed_request_count + failed_request_count,
            "success_count": completed_request_count,
            "error_count": failed_request_count,
            "timeout_count": 0,
            "idle_poll_sleep_count": status["idle_poll_sleep_count"],
            "mailbox": status["mailbox"],
            "executor": status["executor"],
            "recent_poller_error": status["recent_poller_error"],
            "recent_request_error": status["recent_request_error"],
            "latest_timings": status["latest_timings"],
        }
