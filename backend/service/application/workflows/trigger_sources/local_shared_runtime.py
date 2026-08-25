"""本机共享内存 Trigger 的路由、单在途与严格有界执行器原语。"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import json
from threading import BoundedSemaphore, Lock
from typing import Callable, TypeVar
from uuid import uuid4

from backend.service.application.errors import (
    InvalidRequestError,
    WorkflowTriggerExecutorBusyError,
    WorkflowTriggerSourceBusyError,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    require_trigger_response_plan,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


_Result = TypeVar("_Result")


@dataclass(frozen=True)
class WorkflowTriggerRoute:
    """固定一次 mailbox request 使用的 TriggerSource 路由快照。"""

    trigger_source: WorkflowTriggerSource
    route_generation: int
    route_fingerprint: str


@dataclass(frozen=True)
class WorkflowTriggerSourcePermit:
    """表示同一 TriggerSource 完整协议交付期间的唯一在途 permit。"""

    permit_id: str
    trigger_source_id: str
    route_generation: int
    request_id: str


@dataclass(frozen=True)
class WorkflowTriggerExecutorPermit:
    """表示已经计入严格有界容量但尚未提交的 executor permit。"""

    permit_id: str


class WorkflowTriggerRouteRegistry:
    """保存全局路由快照，并以 CAS identity 管理每 source 单在途请求。"""

    def __init__(self) -> None:
        """初始化空 registry；登记 idle source 不分配 LocalBuffer。"""

        self._routes: dict[str, WorkflowTriggerRoute] = {}
        self._active_permits: dict[str, WorkflowTriggerSourcePermit] = {}
        self._lock = Lock()

    def register(self, trigger_source: WorkflowTriggerSource) -> WorkflowTriggerRoute:
        """登记或替换一条已启用 source 路由，并按内容变化推进 generation。"""

        if not trigger_source.enabled or trigger_source.desired_state != "running":
            raise InvalidRequestError("只能登记已启用且期望运行的 TriggerSource")
        fingerprint = _build_route_fingerprint(trigger_source)
        response_plan = require_trigger_response_plan(trigger_source.metadata)
        with self._lock:
            previous = self._routes.get(trigger_source.trigger_source_id)
            if (
                previous is not None
                and previous.route_generation == response_plan.plan_generation
                and previous.route_fingerprint != fingerprint
            ):
                raise InvalidRequestError(
                    "Workflow TriggerSource 配置变化但 response plan generation 未推进"
                )
            generation = response_plan.plan_generation
            route = WorkflowTriggerRoute(
                trigger_source=trigger_source,
                route_generation=generation,
                route_fingerprint=fingerprint,
            )
            self._routes[trigger_source.trigger_source_id] = route
            return route

    def unregister(self, trigger_source_id: str) -> None:
        """停止接收新请求；已取得的 permit 继续按自身 identity 结束。"""

        normalized_id = _require_text(trigger_source_id, "trigger_source_id")
        with self._lock:
            self._routes.pop(normalized_id, None)

    def get_route(
        self,
        *,
        trigger_source_id: str,
        expected_generation: int,
    ) -> WorkflowTriggerRoute:
        """按 source id 和 mailbox 携带的 generation 读取固定路由。"""

        normalized_id = _require_text(trigger_source_id, "trigger_source_id")
        with self._lock:
            route = self._routes.get(normalized_id)
        if route is None:
            raise InvalidRequestError(
                "Workflow TriggerSource 路由不存在",
                details={"trigger_source_id": normalized_id},
            )
        if route.route_generation != expected_generation:
            raise InvalidRequestError(
                "Workflow TriggerSource route generation 已变化",
                details={
                    "trigger_source_id": normalized_id,
                    "expected_generation": expected_generation,
                    "actual_generation": route.route_generation,
                },
            )
        return route

    def acquire_source_permit(
        self,
        *,
        route: WorkflowTriggerRoute,
        request_id: str,
    ) -> WorkflowTriggerSourcePermit:
        """非阻塞取得同一 source 的唯一在途 permit。"""

        normalized_request_id = _require_text(request_id, "request_id")
        source_id = route.trigger_source.trigger_source_id
        with self._lock:
            current_route = self._routes.get(source_id)
            if current_route != route:
                raise InvalidRequestError(
                    "Workflow TriggerSource 路由已变化",
                    details={"trigger_source_id": source_id},
                )
            if source_id in self._active_permits:
                raise WorkflowTriggerSourceBusyError(
                    details={"trigger_source_id": source_id}
                )
            permit = WorkflowTriggerSourcePermit(
                permit_id=f"workflow-trigger-source-permit-{uuid4().hex}",
                trigger_source_id=source_id,
                route_generation=route.route_generation,
                request_id=normalized_request_id,
            )
            self._active_permits[source_id] = permit
            return permit

    def release_source_permit(self, permit: WorkflowTriggerSourcePermit) -> bool:
        """只允许完整 permit identity 释放；迟到旧 completion 返回 False。"""

        with self._lock:
            current = self._active_permits.get(permit.trigger_source_id)
            if current != permit:
                return False
            self._active_permits.pop(permit.trigger_source_id, None)
            return True

    def build_status(self) -> dict[str, int]:
        """返回路由和当前在途 source 数量，不读取图片或参数。"""

        with self._lock:
            return {
                "route_count": len(self._routes),
                "active_source_permit_count": len(self._active_permits),
            }


class BoundedWorkflowTriggerExecutor:
    """提交前抢占 permit 的固定 worker executor，不形成隐藏等待队列。"""

    def __init__(self, *, max_workers: int) -> None:
        """创建 worker 数和最大在途任务数相同的执行器。"""

        if max_workers <= 0:
            raise ValueError("max_workers 必须大于 0")
        self.max_workers = max_workers
        self._permits = BoundedSemaphore(max_workers)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="workflow-trigger",
        )
        self._active_count = 0
        self._active_permit_ids: set[str] = set()
        self._closed = False
        self._lock = Lock()

    def submit(self, callback: Callable[[], _Result]) -> Future[_Result]:
        """非阻塞提交；没有 permit 时直接返回稳定 busy 错误。"""

        permit = self.reserve()
        return self.submit_reserved(permit, callback)

    def reserve(self) -> WorkflowTriggerExecutorPermit:
        """在 worker submit 前非阻塞预留一个严格容量 permit。"""

        with self._lock:
            if self._closed:
                raise InvalidRequestError("Workflow Trigger 执行器已关闭")
            if not self._permits.acquire(blocking=False):
                raise WorkflowTriggerExecutorBusyError(
                    details={"max_workers": self.max_workers}
                )
            self._active_count += 1
            permit = WorkflowTriggerExecutorPermit(
                permit_id=f"workflow-trigger-executor-permit-{uuid4().hex}"
            )
            self._active_permit_ids.add(permit.permit_id)
            return permit

    def submit_reserved(
        self,
        permit: WorkflowTriggerExecutorPermit,
        callback: Callable[[], _Result],
    ) -> Future[_Result]:
        """提交已经预留容量的任务；提交失败时立即归还 permit。"""

        with self._lock:
            if permit.permit_id not in self._active_permit_ids:
                raise InvalidRequestError("Workflow Trigger executor permit 已失效")
        try:
            return self._executor.submit(self._run_with_permit, permit, callback)
        except Exception:
            self.release_reserved(permit)
            raise

    def release_reserved(self, permit: WorkflowTriggerExecutorPermit) -> bool:
        """worker submit 前失败时按 permit identity 归还容量。"""

        return self._release_permit(permit)

    def build_status(self) -> dict[str, int | bool]:
        """返回执行器固定容量状态。"""

        with self._lock:
            return {
                "max_workers": self.max_workers,
                "active_count": self._active_count,
                "available_count": self.max_workers - self._active_count,
                "closed": self._closed,
            }

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        """停止接收新任务，并按调用方选择等待已提交任务。"""

        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def _run_with_permit(
        self,
        permit: WorkflowTriggerExecutorPermit,
        callback: Callable[[], _Result],
    ) -> _Result:
        """执行任务并在任意终态释放 permit。"""

        try:
            return callback()
        finally:
            self._release_permit(permit)

    def _release_permit(self, permit: WorkflowTriggerExecutorPermit) -> bool:
        """归还一次执行器 permit。"""

        with self._lock:
            if permit.permit_id not in self._active_permit_ids:
                return False
            self._active_permit_ids.remove(permit.permit_id)
            self._active_count -= 1
            self._permits.release()
            return True


def _build_route_fingerprint(trigger_source: WorkflowTriggerSource) -> str:
    """只对会改变生产路由语义的字段生成稳定摘要。"""

    payload = {
        "trigger_source_id": trigger_source.trigger_source_id,
        "project_id": trigger_source.project_id,
        "workflow_runtime_id": trigger_source.workflow_runtime_id,
        "submit_mode": trigger_source.submit_mode,
        "transport_config": trigger_source.transport_config,
        "input_binding_mapping": trigger_source.input_binding_mapping,
        "result_mapping": trigger_source.result_mapping,
        "default_execution_metadata": trigger_source.default_execution_metadata,
        "reply_timeout_seconds": trigger_source.reply_timeout_seconds,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


def _require_text(value: str, field_name: str) -> str:
    """校验并返回非空字符串。"""

    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized
