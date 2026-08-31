"""全局 Workflow Trigger mailbox 的路由、准入、handoff 与执行监督器。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import logging
from math import ceil
from threading import Event, Lock, Thread
from time import monotonic_ns, perf_counter, sleep
from typing import Callable

from pydantic import ValidationError

from backend.contracts.buffers import BufferRef
from backend.contracts.buffers.lease_ownership import (
    ExternalBufferAllocation,
    LeaseOwnershipReceipt,
)
from backend.contracts.ipc import workflow_trigger_mailbox_v1 as mailbox_contract
from backend.contracts.workflows import (
    TriggerEventContract,
    WorkflowTriggerAllocationV1,
    WorkflowTriggerEventRequestV1,
    WorkflowTriggerPrepareV1,
    WorkflowTriggerRequestV1,
)
from backend.service.application.errors import (
    InvalidRequestError,
    LocalBufferCapacityError,
    OperationCancelledError,
    OperationTimeoutError,
    ServiceError,
    WorkflowRuntimeBusyError,
    WorkflowTriggerExecutorBusyError,
    WorkflowTriggerSourceBusyError,
)
from backend.service.application.local_buffers import LocalBufferBrokerClient
from backend.service.application.workflows.execution_cleanup import (
    register_local_buffer_lease_cleanup,
)
from backend.service.application.workflows.runtime.invokes import (
    WorkflowRuntimeInvokeRequest,
)
from backend.service.application.workflows.runtime.policies import (
    should_return_workflow_timing_metadata,
)
from backend.service.application.workflows.runtime_service import (
    WorkflowRuntimeService,
    WorkflowRuntimeSyncAdmission,
)
from backend.service.application.workflows.trigger_sources.input_binding_mapper import (
    InputBindingMapper,
)
from backend.service.application.workflows.trigger_sources.local_shared_runtime import (
    BoundedWorkflowTriggerExecutor,
    WorkflowTriggerExecutorPermit,
    WorkflowTriggerRoute,
    WorkflowTriggerRouteRegistry,
    WorkflowTriggerSourcePermit,
)
from backend.service.application.workflows.trigger_sources.result_dispatcher import (
    WorkflowResultDispatcher,
)
from backend.service.application.workflows.trigger_sources.error_classification import (
    BUSY_ERROR_CODES,
    CAPACITY_ERROR_CODES,
    read_trigger_result_error_code,
)
from backend.service.application.workflows.trigger_sources.trigger_message_channel import (
    EVENT_REQUEST_SCHEMA_ID,
    WorkflowTriggerDescriptorIdentity,
    WorkflowTriggerMailboxRequest,
    WorkflowTriggerMailboxServerPort,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY,
    PreparedTriggerResult,
    build_workflow_output_delivery_plan,
    list_prepared_result_ownership_receipts,
    require_trigger_response_plan,
)
from backend.service.application.workflows.trigger_sources.workflow_submitter import (
    WorkflowTriggerSubmitRequest,
    build_trigger_execution_metadata,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


logger = logging.getLogger(__name__)


@dataclass
class _PendingMailboxRequest:
    """保存 descriptor 外部的权威路由、permit 和 private receipt。"""

    identity: WorkflowTriggerDescriptorIdentity
    trigger_source_id: str
    event_id: str
    route: WorkflowTriggerRoute
    source_permit: WorkflowTriggerSourcePermit
    prepare: WorkflowTriggerPrepareV1 | None = None
    allocation: ExternalBufferAllocation | None = None
    current_receipt: LeaseOwnershipReceipt | None = None
    trigger_event: TriggerEventContract | None = None
    admission: WorkflowRuntimeSyncAdmission | None = None
    executor_permit: WorkflowTriggerExecutorPermit | None = None
    cancel_event: Event | None = None
    task_active: bool = False
    protocol_terminal: bool = False
    cleanup_started: bool = False
    outcome_recorded: bool = False
    terminal_categories: set[str] = field(default_factory=set)
    output_receipts: tuple[LeaseOwnershipReceipt, ...] = ()
    started_at: float = field(default_factory=perf_counter)
    writing_published_at: float | None = None
    executor_submitted_at: float | None = None
    timings: dict[str, float] = field(default_factory=dict)


@dataclass
class _SourceMailboxHealth:
    """保存单个 TriggerSource 的无内容运行计数。"""

    last_triggered_at: str | None = None
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    busy_count: int = 0
    capacity_reject_count: int = 0
    request_timeout_count: int = 0
    response_ack_timeout_count: int = 0
    cancel_count: int = 0
    recent_error: dict[str, object] | None = None


class WorkflowTriggerMailboxSupervisor:
    """持有单 mailbox owner，并把 poller 与 Workflow 执行严格解耦。"""

    def __init__(
        self,
        *,
        mailbox: WorkflowTriggerMailboxServerPort | None = None,
        mailbox_provider: (
            Callable[[], WorkflowTriggerMailboxServerPort] | None
        ) = None,
        runtime_service: WorkflowRuntimeService,
        local_buffer_client: LocalBufferBrokerClient | None = None,
        local_buffer_client_provider: (
            Callable[[], LocalBufferBrokerClient | None] | None
        ) = None,
        max_executor_workers: int,
        poll_interval_seconds: float = 0.001,
        response_ack_timeout_seconds: float = 30.0,
        cancellation_grace_seconds: float = 0.0,
    ) -> None:
        """初始化全局 mailbox、route registry 和无隐藏队列 executor。"""

        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        if response_ack_timeout_seconds <= 0:
            raise ValueError("response_ack_timeout_seconds 必须大于 0")
        if cancellation_grace_seconds < 0:
            raise ValueError("cancellation_grace_seconds 不能小于 0")
        if local_buffer_client is None and local_buffer_client_provider is None:
            raise ValueError(
                "local_buffer_client 与 local_buffer_client_provider 至少提供一个"
            )
        if (mailbox is None) == (mailbox_provider is None):
            raise ValueError("mailbox 与 mailbox_provider 必须且只能提供一个")
        self.runtime_service = runtime_service
        self._local_buffer_client = local_buffer_client
        self._local_buffer_client_provider = local_buffer_client_provider
        self._owns_local_buffer_client = local_buffer_client is None
        self._mailbox: WorkflowTriggerMailboxServerPort | None = mailbox
        self._mailbox_provider = mailbox_provider
        self._mailbox_creation_lock = Lock()
        self._mailbox_closed = False
        self.routes = WorkflowTriggerRouteRegistry()
        self._max_executor_workers = max_executor_workers
        self.executor = BoundedWorkflowTriggerExecutor(max_workers=max_executor_workers)
        self._executor_closed = False
        self.input_binding_mapper = InputBindingMapper()
        self.result_dispatcher = WorkflowResultDispatcher()
        self.poll_interval_seconds = poll_interval_seconds
        self.response_ack_timeout_seconds = response_ack_timeout_seconds
        self.cancellation_grace_seconds = cancellation_grace_seconds
        self._pending: dict[
            WorkflowTriggerDescriptorIdentity,
            _PendingMailboxRequest,
        ] = {}
        self._pending_lock = Lock()
        self._recent_poller_error: dict[str, object] | None = None
        self._recent_request_error: dict[str, object] | None = None
        self._latest_timings: dict[str, float] = {}
        self._completed_request_count = 0
        self._failed_request_count = 0
        self._source_health: dict[str, _SourceMailboxHealth] = {}
        self._registered_source_ids: set[str] = set()
        self._idle_poll_sleep_count = 0
        self._orphan_sweep_cursor = 0
        self._stop_event = Event()
        self._thread: Thread | None = None

    @property
    def mailbox(self) -> WorkflowTriggerMailboxServerPort:
        """在服务 lifespan 启动后惰性取得唯一 mailbox owner。"""

        mailbox = self._mailbox
        if mailbox is not None:
            return mailbox
        with self._mailbox_creation_lock:
            if self._mailbox_closed:
                raise RuntimeError("Workflow Trigger mailbox supervisor 已关闭")
            mailbox = self._mailbox
            if mailbox is None:
                provider = self._mailbox_provider
                if provider is None:
                    raise RuntimeError("Workflow Trigger mailbox provider 不存在")
                mailbox = provider()
                self._mailbox = mailbox
            return mailbox

    def register_trigger_source(
        self,
        trigger_source: WorkflowTriggerSource,
    ) -> WorkflowTriggerRoute:
        """登记一条本机共享内存 TriggerSource 路由快照。"""

        if trigger_source.trigger_kind != "local-shared-memory":
            raise InvalidRequestError(
                "WorkflowTriggerMailboxSupervisor 只接受 local-shared-memory"
            )
        if trigger_source.submit_mode != "sync":
            raise InvalidRequestError("local-shared-memory 仅支持 sync submit_mode")
        if trigger_source.reply_timeout_seconds is None:
            raise InvalidRequestError(
                "local-shared-memory sync TriggerSource 必须固定 reply_timeout_seconds"
            )
        response_plan = require_trigger_response_plan(trigger_source.metadata)
        if (
            response_plan.response_ack_timeout_seconds
            != self.response_ack_timeout_seconds
        ):
            raise InvalidRequestError(
                "local-shared-memory response plan ACK timeout 与服务配置不一致",
                details={
                    "plan_response_ack_timeout_seconds": (
                        response_plan.response_ack_timeout_seconds
                    ),
                    "configured_response_ack_timeout_seconds": (
                        self.response_ack_timeout_seconds
                    ),
                },
            )
        route = self.routes.register(trigger_source)
        with self._pending_lock:
            self._registered_source_ids.add(trigger_source.trigger_source_id)
            self._source_health.setdefault(
                trigger_source.trigger_source_id,
                _SourceMailboxHealth(),
            )
        return route

    def unregister_trigger_source(self, trigger_source_id: str) -> None:
        """停止一条 source 的新 PREPARE，不中断已有请求。"""

        self.routes.unregister(trigger_source_id)
        normalized_id = trigger_source_id.strip()
        with self._pending_lock:
            self._registered_source_ids.discard(normalized_id)
            self._prune_source_health_locked(normalized_id)

    def start(self) -> None:
        """启动唯一 poller；重复调用保持幂等。"""

        if self._thread is not None and self._thread.is_alive():
            return
        if self._mailbox_closed:
            raise RuntimeError("Workflow Trigger mailbox supervisor 已关闭")
        self._require_local_buffer_client()
        self.mailbox
        if self._executor_closed:
            self.executor = BoundedWorkflowTriggerExecutor(
                max_workers=self._max_executor_workers
            )
            self._executor_closed = False
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name="workflow-trigger-mailbox",
            daemon=True,
        )
        self._thread.start()

    def process_once(self) -> bool:
        """处理至多一个 PREPARE、一个 REQUEST 和一轮 terminal sweep。"""

        progressed = False
        prepare = self.mailbox.poll_prepare()
        if prepare is not None:
            progressed = True
            self._handle_prepare(
                prepare.identity,
                prepare.payload,
                prepare.route_generation,
                prepare.accepted_timeout_ms,
            )
        request_poll_started_at = perf_counter()
        request = self.mailbox.poll_request()
        if request is not None:
            progressed = True
            if request.request_schema_id == EVENT_REQUEST_SCHEMA_ID:
                self._handle_event_request(
                    request,
                    request_detect_ms=_elapsed_ms(request_poll_started_at),
                )
            else:
                self._handle_request(
                    request,
                    request_detect_ms=_elapsed_ms(request_poll_started_at),
                )
        with self._pending_lock:
            active_descriptor_indexes = tuple(
                identity.descriptor_index for identity in self._pending
            )
        orphan_descriptor_index = self._orphan_sweep_cursor
        self._orphan_sweep_cursor = (
            self._orphan_sweep_cursor + 1
        ) % mailbox_contract.DESCRIPTOR_COUNT
        sweep_result = self.mailbox.sweep(
            descriptor_indexes=(
                *active_descriptor_indexes,
                orphan_descriptor_index,
            )
        )
        for key, protocol_terminal in (
            ("cancelled_identities", True),
            ("deadline_exceeded_identities", False),
            ("response_ack_timeout_identities", True),
        ):
            identities = sweep_result.get(key)
            if not isinstance(identities, tuple):
                continue
            for identity in identities:
                if not isinstance(identity, WorkflowTriggerDescriptorIdentity):
                    continue
                progressed = True
                self._record_terminal_category(identity, category=key)
                self._signal_request_cancel(
                    identity,
                    protocol_terminal=protocol_terminal,
                )
        released_identities = sweep_result.get("released_identities")
        if isinstance(released_identities, tuple):
            for identity in released_identities:
                if isinstance(identity, WorkflowTriggerDescriptorIdentity):
                    progressed = True
                    self._mark_protocol_terminal(identity)
        return progressed

    def build_status(self) -> dict[str, object]:
        """返回不含图片、路径和业务参数的容量摘要。"""

        with self._pending_lock:
            pending_count = len(self._pending)
            active_task_count = sum(item.task_active for item in self._pending.values())
            recent_poller_error = (
                dict(self._recent_poller_error)
                if self._recent_poller_error is not None
                else None
            )
            recent_request_error = (
                dict(self._recent_request_error)
                if self._recent_request_error is not None
                else None
            )
            completed_request_count = self._completed_request_count
            failed_request_count = self._failed_request_count
            source_health_entry_count = len(self._source_health)
            idle_poll_sleep_count = self._idle_poll_sleep_count
            latest_timings = dict(self._latest_timings)
        mailbox_status = dict(self.mailbox.build_status())
        mailbox_status.pop("path", None)
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "pending_request_count": pending_count,
            "active_task_count": active_task_count,
            "mailbox": mailbox_status,
            "routes": self.routes.build_status(),
            "executor": self.executor.build_status(),
            "recent_poller_error": recent_poller_error,
            "recent_request_error": recent_request_error,
            "completed_request_count": completed_request_count,
            "failed_request_count": failed_request_count,
            "source_health_entry_count": source_health_entry_count,
            "idle_poll_sleep_count": idle_poll_sleep_count,
            "latest_timings": latest_timings,
        }

    def build_source_status(self, trigger_source_id: str) -> dict[str, object]:
        """返回严格按 TriggerSource 隔离的计数和当前在途数。"""

        with self._pending_lock:
            counters = self._source_health.get(
                trigger_source_id,
                _SourceMailboxHealth(),
            )
            pending = tuple(
                item
                for item in self._pending.values()
                if item.trigger_source_id == trigger_source_id
            )
            return {
                "source_scoped": True,
                "last_triggered_at": counters.last_triggered_at,
                "request_count": counters.request_count,
                "success_count": counters.success_count,
                "error_count": counters.error_count,
                "timeout_count": counters.timeout_count,
                "busy_count": counters.busy_count,
                "capacity_reject_count": counters.capacity_reject_count,
                "request_timeout_count": counters.request_timeout_count,
                "response_ack_timeout_count": (counters.response_ack_timeout_count),
                "cancel_count": counters.cancel_count,
                "pending_request_count": len(pending),
                "active_task_count": sum(item.task_active for item in pending),
                "recent_error": (
                    dict(counters.recent_error)
                    if counters.recent_error is not None
                    else None
                ),
            }

    def stop(self) -> None:
        """停止当前运行代；provider 模式允许下一次 lifespan 重新启动。"""

        self._stop(permanent=False)

    def close(self) -> None:
        """永久关闭 supervisor，不再允许创建新的 mailbox owner。"""

        self._stop(permanent=True)

    def _stop(self, *, permanent: bool) -> None:
        """结束 poller、执行器和当前 owner，并按模式保留可重启依赖。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None
        if not self._executor_closed:
            self.executor.shutdown(wait=True, cancel_futures=False)
            self._executor_closed = True
        with self._pending_lock:
            identities = tuple(self._pending)
        for identity in identities:
            self._cleanup_pending(identity)
        mailbox = self._mailbox
        self._mailbox = None
        self._mailbox_closed = permanent or self._mailbox_provider is None
        if mailbox is not None:
            mailbox.close()
        if self._owns_local_buffer_client:
            client = self._local_buffer_client
            self._local_buffer_client = None
            if client is not None:
                client.close()

    def _run(self) -> None:
        """持续轮询；poller 从不等待 Workflow future。"""

        while not self._stop_event.is_set():
            try:
                if not self.process_once():
                    with self._pending_lock:
                        self._idle_poll_sleep_count += 1
                    sleep(self.poll_interval_seconds)
            except Exception as error:
                logger.exception("Workflow Trigger mailbox poller 发生异常")
                with self._pending_lock:
                    self._recent_poller_error = {
                        "error_type": type(error).__name__,
                        "error_code": getattr(error, "code", "protocol_error"),
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                    }
                sleep(self.poll_interval_seconds)

    def _handle_prepare(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        payload: bytes,
        route_generation: int,
        accepted_timeout_ms: int,
    ) -> None:
        """固定路由、取得 source permit 并分配精确 input lease。"""

        pending: _PendingMailboxRequest | None = None
        source_id: str | None = None
        prepare_started_at = perf_counter()
        try:
            prepare_decode_started_at = perf_counter()
            prepare = WorkflowTriggerPrepareV1.model_validate_json(payload)
            route = self.routes.get_route(
                trigger_source_id=prepare.trigger_source_id,
                expected_generation=route_generation,
            )
            source_id = prepare.trigger_source_id
            self._record_source_request(source_id)
            identity = self.mailbox.tighten_accepted_timeout(
                identity=identity,
                timeout_ms=min(
                    accepted_timeout_ms,
                    int(route.trigger_source.reply_timeout_seconds * 1_000),
                ),
            )
            source_permit = self.routes.acquire_source_permit(
                route=route,
                request_id=str(identity.request_id),
            )
            pending = _PendingMailboxRequest(
                identity=identity,
                trigger_source_id=prepare.trigger_source_id,
                event_id=prepare.event_id,
                prepare=prepare,
                route=route,
                source_permit=source_permit,
            )
            pending.timings["prepare_decode_route_admission_ms"] = _elapsed_ms(
                prepare_decode_started_at
            )
            with self._pending_lock:
                self._pending[identity] = pending
            broker_allocate_started_at = perf_counter()
            allocation = self._require_local_buffer_client().allocate_external_buffer(
                content_length=prepare.image.content_length,
                owner_kind="workflow-trigger-write",
                owner_id=(f"{prepare.trigger_source_id}:{identity.request_id.hex}"),
                deadline_ns=identity.deadline_ns,
                trace_id=prepare.event_id,
            )
            pending.timings["broker_allocate_ms"] = _elapsed_ms(
                broker_allocate_started_at
            )
            pending.allocation = allocation
            pending.current_receipt = allocation.receipt
            allocation_contract = WorkflowTriggerAllocationV1(
                arena_id=allocation.lease.arena_id,
                lease_id=allocation.lease.lease_id,
                buffer_id=allocation.lease.buffer_id,
                descriptor_index=allocation.lease.descriptor_index,
                descriptor_generation=allocation.lease.descriptor_generation,
                broker_epoch=allocation.lease.broker_epoch,
                layout_fingerprint=allocation.receipt.layout_fingerprint,
                offset=allocation.lease.offset,
                content_length=allocation.lease.content_length,
                allocation_capacity_bytes=(allocation.lease.allocation_capacity_bytes),
            )
            mailbox_publish_writing_started_at = perf_counter()
            self.mailbox.publish_writing(
                identity=identity,
                allocation_payload=allocation_contract.model_dump_json().encode(
                    "utf-8"
                ),
            )
            pending.timings["mailbox_publish_writing_ms"] = _elapsed_ms(
                mailbox_publish_writing_started_at
            )
            pending.timings["mailbox_prepare_ms"] = _elapsed_ms(prepare_started_at)
            pending.writing_published_at = perf_counter()
        except Exception as error:
            if pending is not None and pending.current_receipt is not None:
                self._release_receipt(pending.current_receipt)
                pending.current_receipt = None
            self._publish_failure(
                identity,
                error,
                pending=pending,
                source_id=source_id,
            )

    def _handle_request(
        self,
        request: WorkflowTriggerMailboxRequest,
        *,
        request_detect_ms: float,
    ) -> None:
        """commit 图片、完成真实 Runtime/executor admission 和首次 owner handoff。"""

        pending = self._get_pending(request.identity)
        if pending is None:
            self._publish_failure(
                request.identity,
                InvalidRequestError("Workflow Trigger PREPARE 上下文不存在"),
                pending=None,
            )
            return
        pending.timings["mailbox_request_detect_ms"] = request_detect_ms
        request_admission_started_at = perf_counter()
        if pending.writing_published_at is not None:
            pending.timings["input_publish_wait_ms"] = _elapsed_ms(
                pending.writing_published_at
            )
        try:
            request_decode_started_at = perf_counter()
            request_contract = WorkflowTriggerRequestV1.model_validate_json(
                request.payload
            )
            self._validate_request_identity(pending, request_contract)
            self._raise_if_request_terminal(pending)
            pending.timings["request_decode_validate_ms"] = _elapsed_ms(
                request_decode_started_at
            )
            prepare = pending.prepare
            if prepare is None:
                raise InvalidRequestError("Workflow Trigger 图片 PREPARE 上下文不存在")
            if pending.current_receipt is None:
                raise InvalidRequestError("Workflow Trigger input lease receipt 不存在")
            provisional_buffer_ref = self._build_provisional_input_buffer_ref(pending)
            trigger_event = self._build_trigger_event(
                pending,
                request_contract,
                provisional_buffer_ref,
            )
            pending.trigger_event = trigger_event
            input_binding_started_at = perf_counter()
            input_bindings = self.input_binding_mapper.map_input_bindings(
                trigger_source=pending.route.trigger_source,
                trigger_event=trigger_event,
            )
            submit_request = WorkflowTriggerSubmitRequest(
                trigger_source=pending.route.trigger_source,
                trigger_event=trigger_event,
                created_by=pending.route.trigger_source.created_by,
            )
            pending.timings["input_binding_map_ms"] = _elapsed_ms(
                input_binding_started_at
            )
            runtime_admission_started_at = perf_counter()
            remaining_ns = request.identity.deadline_ns - monotonic_ns()
            if remaining_ns <= 0:
                raise OperationTimeoutError("Workflow Trigger request deadline 已到期")
            admission = self.runtime_service.admit_sync_workflow_run(
                pending.route.trigger_source.workflow_runtime_id,
                WorkflowRuntimeInvokeRequest(
                    input_bindings=input_bindings,
                    execution_metadata=build_trigger_execution_metadata(submit_request),
                    # Runtime 的秒级公开契约只作为 worker 内部上限；mailbox
                    # cancel_event 继续以同一个纳秒绝对 deadline 负责精确截止。
                    timeout_seconds=max(1, ceil(remaining_ns / 1_000_000_000)),
                ),
                created_by=pending.route.trigger_source.created_by,
                execution_acquisition_mode="reject",
                cancellation_grace_seconds=self.cancellation_grace_seconds,
            )
            pending.timings["runtime_admission_ms"] = _elapsed_ms(
                runtime_admission_started_at
            )
            pending.admission = admission
            pending.cancel_event = admission.cancel_event
            self._raise_if_request_terminal(pending)
            executor_reserve_started_at = perf_counter()
            executor_permit = self.executor.reserve()
            pending.timings["executor_reserve_ms"] = _elapsed_ms(
                executor_reserve_started_at
            )
            pending.executor_permit = executor_permit
            self._raise_if_request_terminal(pending)
            commit_handoff_started_at = perf_counter()
            committed = self._require_local_buffer_client().publish_and_transfer_external_buffer(
                receipt=pending.current_receipt,
                media_type=prepare.image.media_type,
                new_owner_kind="workflow-runtime",
                new_owner_id=(
                    f"{admission.workflow_run.workflow_run_id}:"
                    f"{admission.workflow_app_runtime.workflow_runtime_id}:"
                    f"{request.identity.request_id.hex}"
                ),
                deadline_ns=request.identity.deadline_ns,
                shape=prepare.image.shape,
                dtype=prepare.image.dtype,
                layout=prepare.image.layout,
                pixel_format=prepare.image.pixel_format,
            )
            pending.timings["broker_commit_owner_handoff_ms"] = _elapsed_ms(
                commit_handoff_started_at
            )
            runtime_receipt = committed.receipt
            pending.current_receipt = runtime_receipt
            if committed.buffer_ref != provisional_buffer_ref:
                raise InvalidRequestError(
                    "LocalBufferBroker commit 结果与 PREPARE allocation 不一致"
                )
            execution_metadata = dict(admission.execution_metadata)
            response_plan = require_trigger_response_plan(
                pending.route.trigger_source.metadata
            )
            execution_metadata[WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY] = (
                build_workflow_output_delivery_plan(
                    response_plan,
                    response_owner_kind="workflow-trigger-response",
                    response_owner_id=_build_response_owner_id(request.identity),
                    deadline_ns=request.identity.deadline_ns,
                ).model_dump(mode="json")
            )
            register_local_buffer_lease_cleanup(
                execution_metadata,
                lease_id=runtime_receipt.lease_id,
                ownership_receipt=runtime_receipt,
            )
            admission = replace(admission, execution_metadata=execution_metadata)
            pending.admission = admission
            pending.task_active = True
            self._raise_if_request_terminal(pending)
            executor_submit_started_at = perf_counter()
            pending.executor_submitted_at = executor_submit_started_at
            # 任务一旦提交即可立即在另一个线程完成，所有需要随响应返回的
            # submit 前诊断必须先写入 pending，避免成功响应漏字段。
            pending.timings["request_admission_submit_ms"] = _elapsed_ms(
                request_admission_started_at
            )
            self.executor.submit_reserved(
                executor_permit,
                lambda: self._execute_pending(request.identity),
            )
            pending.timings["executor_submit_ms"] = _elapsed_ms(
                executor_submit_started_at
            )
        except Exception as error:
            pending.task_active = False
            self._compensate_before_worker_submit(pending, error)
            self._publish_failure(request.identity, error, pending=pending)

    def _handle_event_request(
        self,
        request: WorkflowTriggerMailboxRequest,
        *,
        request_detect_ms: float,
    ) -> None:
        """执行无图片事件请求，并明确跳过 PREPARE、allocation 和 input lease。"""

        pending: _PendingMailboxRequest | None = None
        source_id: str | None = None
        request_started_at = perf_counter()
        try:
            event_request = WorkflowTriggerEventRequestV1.model_validate_json(
                request.payload
            )
            source_id = event_request.trigger_source_id
            route = self.routes.get_route(
                trigger_source_id=source_id,
                expected_generation=request.route_generation,
            )
            self._record_source_request(source_id)
            identity = self.mailbox.tighten_accepted_timeout(
                identity=request.identity,
                timeout_ms=min(
                    request.accepted_timeout_ms,
                    int(route.trigger_source.reply_timeout_seconds * 1_000),
                ),
            )
            source_permit = self.routes.acquire_source_permit(
                route=route,
                request_id=str(identity.request_id),
            )
            pending = _PendingMailboxRequest(
                identity=identity,
                trigger_source_id=source_id,
                event_id=event_request.event_id,
                route=route,
                source_permit=source_permit,
            )
            pending.timings["mailbox_request_detect_ms"] = request_detect_ms
            with self._pending_lock:
                self._pending[identity] = pending
            trigger_event = TriggerEventContract(
                trigger_source_id=source_id,
                trigger_kind="local-shared-memory",
                event_id=event_request.event_id,
                trace_id=event_request.trace_id,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                idempotency_key=event_request.idempotency_key,
                payload=dict(event_request.payload),
                metadata=dict(event_request.metadata),
            )
            pending.trigger_event = trigger_event
            input_binding_started_at = perf_counter()
            input_bindings = self.input_binding_mapper.map_input_bindings(
                trigger_source=route.trigger_source,
                trigger_event=trigger_event,
            )
            submit_request = WorkflowTriggerSubmitRequest(
                trigger_source=route.trigger_source,
                trigger_event=trigger_event,
                created_by=route.trigger_source.created_by,
            )
            pending.timings["input_binding_map_ms"] = _elapsed_ms(
                input_binding_started_at
            )
            self._raise_if_request_terminal(pending)
            remaining_ns = identity.deadline_ns - monotonic_ns()
            if remaining_ns <= 0:
                raise OperationTimeoutError("Workflow Trigger request deadline 已到期")
            runtime_admission_started_at = perf_counter()
            admission = self.runtime_service.admit_sync_workflow_run(
                route.trigger_source.workflow_runtime_id,
                WorkflowRuntimeInvokeRequest(
                    input_bindings=input_bindings,
                    execution_metadata=build_trigger_execution_metadata(submit_request),
                    timeout_seconds=max(1, ceil(remaining_ns / 1_000_000_000)),
                ),
                created_by=route.trigger_source.created_by,
                execution_acquisition_mode="reject",
                cancellation_grace_seconds=self.cancellation_grace_seconds,
            )
            pending.timings["runtime_admission_ms"] = _elapsed_ms(
                runtime_admission_started_at
            )
            pending.admission = admission
            pending.cancel_event = admission.cancel_event
            self._raise_if_request_terminal(pending)
            executor_reserve_started_at = perf_counter()
            executor_permit = self.executor.reserve()
            pending.timings["executor_reserve_ms"] = _elapsed_ms(
                executor_reserve_started_at
            )
            pending.executor_permit = executor_permit
            self._raise_if_request_terminal(pending)
            execution_metadata = dict(admission.execution_metadata)
            response_plan = require_trigger_response_plan(route.trigger_source.metadata)
            execution_metadata[WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY] = (
                build_workflow_output_delivery_plan(
                    response_plan,
                    response_owner_kind="workflow-trigger-response",
                    response_owner_id=_build_response_owner_id(identity),
                    deadline_ns=identity.deadline_ns,
                ).model_dump(mode="json")
            )
            pending.admission = replace(
                admission,
                execution_metadata=execution_metadata,
            )
            pending.task_active = True
            self._raise_if_request_terminal(pending)
            pending.timings["request_admission_submit_ms"] = _elapsed_ms(
                request_started_at
            )
            executor_submit_started_at = perf_counter()
            pending.executor_submitted_at = executor_submit_started_at
            self.executor.submit_reserved(
                executor_permit,
                lambda: self._execute_pending(identity),
            )
            pending.timings["executor_submit_ms"] = _elapsed_ms(
                executor_submit_started_at
            )
        except Exception as error:
            if pending is not None:
                pending.task_active = False
                self._compensate_before_worker_submit(pending, error)
            self._publish_failure(
                pending.identity if pending is not None else request.identity,
                error,
                pending=pending,
                source_id=source_id,
            )

    def _execute_pending(self, identity: WorkflowTriggerDescriptorIdentity) -> None:
        """在有界 worker 中执行 Workflow；完成后只发布结果，不在 poller 等待。"""

        pending = self._get_pending(identity)
        if (
            pending is None
            or pending.admission is None
            or pending.trigger_event is None
        ):
            return
        try:
            if pending.executor_submitted_at is not None:
                pending.timings["executor_start_wait_ms"] = _elapsed_ms(
                    pending.executor_submitted_at
                )
            admission = pending.admission
            # 调用开始后 execution token 的唯一释放责任已移交 RuntimeService；
            # 即使调用抛错，也不能再走 worker-submit 前的 fail_admitted 补偿。
            pending.admission = None
            workflow_runtime_started_at = perf_counter()
            invoke_result = self.runtime_service.invoke_admitted_sync_workflow_run(
                admission
            )
            pending.timings["workflow_runtime_invoke_ms"] = _elapsed_ms(
                workflow_runtime_started_at
            )
            if invoke_result.input_cleanup_completed:
                # Runtime worker/manager 已完成输入 lease cleanup。清除 adapter 的
                # 旧 receipt，避免每个成功请求再向 Broker 发送一次必然 stale 的
                # conditional release；输出 lease 由 output_receipts 独立管理。
                pending.current_receipt = None
            raw_workflow_timings = invoke_result.workflow_run.metadata.get("timings")
            if isinstance(raw_workflow_timings, dict):
                pending.timings.update(_read_numeric_timings(raw_workflow_timings))
            prepared_result = (
                PreparedTriggerResult.model_validate(
                    invoke_result.prepared_trigger_result
                )
                if invoke_result.prepared_trigger_result is not None
                else None
            )
            pending.output_receipts = (
                list_prepared_result_ownership_receipts(prepared_result)
                if prepared_result is not None
                else ()
            )
            result_build_started_at = perf_counter()
            trigger_result = self.result_dispatcher.build_result(
                trigger_source=pending.route.trigger_source,
                trigger_event=pending.trigger_event,
                workflow_run=invoke_result.workflow_run,
                response_outputs=dict(invoke_result.raw_outputs),
                prepared_trigger_result=(
                    prepared_result.model_dump(mode="json")
                    if prepared_result is not None
                    else None
                ),
            )
            pending.timings["trigger_result_build_ms"] = _elapsed_ms(
                result_build_started_at
            )
            error_code = (
                mailbox_contract.ERROR_CODE_NONE
                if trigger_result.state == "succeeded"
                else mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTION_FAILED
            )
            timing_enabled = should_return_workflow_timing_metadata(
                invoke_result.workflow_run.metadata
            )
            if timing_enabled:
                provisional_result = trigger_result.model_copy(
                    update={
                        "metadata": _merge_result_timings(
                            trigger_result.metadata,
                            pending.timings,
                        )
                    }
                )
                serialize_started_at = perf_counter()
                provisional_result.model_dump_json()
                pending.timings["response_json_serialize_ms"] = _elapsed_ms(
                    serialize_started_at
                )
                pending.timings["total_ms"] = _elapsed_ms(pending.started_at)
                trigger_result = trigger_result.model_copy(
                    update={
                        "metadata": _merge_result_timings(
                            trigger_result.metadata,
                            pending.timings,
                        )
                    }
                )
            response_serialize_started_at = perf_counter()
            response_payload = trigger_result.model_dump_json().encode("utf-8")
            pending.timings["response_serialize_ms"] = _elapsed_ms(
                response_serialize_started_at
            )
            self._raise_if_request_terminal(pending)
            response_ack_deadline_ns = self.mailbox.new_response_ack_deadline_ns()
            if pending.output_receipts:
                output_handoff_started_at = perf_counter()
                pending.output_receipts = (
                    self._require_local_buffer_client().transfer_lease_ownership(
                        receipts=pending.output_receipts,
                        new_owner_kind="workflow-trigger-response",
                        new_owner_id=_build_response_owner_id(identity),
                        deadline_ns=response_ack_deadline_ns,
                    )
                )
                pending.timings["response_output_ack_handoff_ms"] = _elapsed_ms(
                    output_handoff_started_at
                )
            mailbox_publish_response_started_at = perf_counter()
            published_error_code = self.mailbox.publish_response(
                identity=identity,
                payload=response_payload,
                error_code=error_code,
                response_output_lease_count=len(pending.output_receipts),
                handoff_state=(
                    mailbox_contract.HANDOFF_STATE_COMPLETE
                    if pending.output_receipts
                    else mailbox_contract.HANDOFF_STATE_NONE
                ),
                response_ack_deadline_ns=response_ack_deadline_ns,
            )
            pending.timings["mailbox_publish_response_ms"] = _elapsed_ms(
                mailbox_publish_response_started_at
            )
            if published_error_code != error_code:
                # page capacity/deadline/cancel 的紧凑响应不携带图片 locator；
                # 已完成 handoff 的 lease 必须立即按新 receipt 回收。
                self._release_output_receipts(pending)
            self._record_request_observation(
                pending,
                workflow_state=trigger_result.state,
                published_error_code=published_error_code,
                workflow_error_code=read_trigger_result_error_code(trigger_result),
            )
        except Exception as error:
            # 错误 RESPONSE 不公开任何图片 locator。先回收当前 input/output
            # receipt，再发布客户端可见终态，避免终态已返回但容量仍显示 active。
            self._release_output_receipts(pending)
            self._release_receipt_if_present(pending)
            self._publish_failure(
                identity,
                error,
                pending=pending,
                capacity_error_code=(
                    mailbox_contract.ERROR_CODE_LOCAL_BUFFER_OUTPUT_CAPACITY_EXHAUSTED
                ),
            )
        finally:
            pending.executor_permit = None
            self._release_receipt_if_present(pending)
            with self._pending_lock:
                pending.task_active = False
                should_cleanup = pending.protocol_terminal
            if should_cleanup:
                self._cleanup_pending(identity)

    def _compensate_before_worker_submit(
        self,
        pending: _PendingMailboxRequest,
        error: Exception,
    ) -> None:
        """按当前权威 receipt 逆序补偿 executor、Runtime 和 LocalBuffer。"""

        if pending.executor_permit is not None:
            released = self._run_cleanup_step(
                pending.identity,
                step="executor-permit-before-submit",
                callback=lambda: self.executor.release_reserved(
                    pending.executor_permit
                ),
            )
            if released:
                pending.executor_permit = None
        if pending.admission is not None:
            compensated = self._run_cleanup_step(
                pending.identity,
                step="runtime-admission-before-submit",
                callback=lambda: self.runtime_service.fail_admitted_sync_workflow_run(
                    pending.admission,
                    error=error,
                ),
            )
            if compensated:
                pending.admission = None
        self._run_cleanup_step(
            pending.identity,
            step="input-lease-before-submit",
            callback=lambda: self._release_receipt_if_present(pending),
        )

    def _build_trigger_event(
        self,
        pending: _PendingMailboxRequest,
        request: WorkflowTriggerRequestV1,
        buffer_ref: BufferRef,
    ) -> TriggerEventContract:
        """把 committed BufferRef 放入受 route mapping 约束的事件 payload。"""

        prepare = pending.prepare
        if prepare is None:
            raise InvalidRequestError("Workflow Trigger 图片 PREPARE 上下文不存在")
        event_payload = dict(request.payload)
        event_payload[prepare.image.event_payload_key] = {
            "transport_kind": "buffer",
            # image-ref.v1 的公开 schema 要求顶层 media_type。BufferRef 内虽然也
            # 保存该字段，但不能让公开输入契约依赖定位器内部的重复元数据。
            "media_type": prepare.image.media_type,
            "buffer_ref": buffer_ref.model_dump(mode="json"),
        }
        return TriggerEventContract(
            trigger_source_id=request.trigger_source_id,
            trigger_kind="local-shared-memory",
            event_id=request.event_id,
            trace_id=request.trace_id,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            idempotency_key=request.idempotency_key,
            payload=event_payload,
            metadata=dict(request.metadata),
        )

    @staticmethod
    def _build_provisional_input_buffer_ref(
        pending: _PendingMailboxRequest,
    ) -> BufferRef:
        """按 PREPARE 已固定的 allocation 构造 admission 用定位引用。

        该引用不会在 commit 前提交给 worker；Broker 原子 commit/handoff
        返回后必须与它完全一致，才允许提交执行。
        """

        allocation = pending.allocation
        if allocation is None:
            raise InvalidRequestError("Workflow Trigger input allocation 不存在")
        lease = allocation.lease
        prepare = pending.prepare
        if prepare is None:
            raise InvalidRequestError("Workflow Trigger 图片 PREPARE 上下文不存在")
        image = prepare.image
        return BufferRef(
            buffer_id=lease.buffer_id,
            lease_id=lease.lease_id,
            arena_id=lease.arena_id,
            descriptor_index=lease.descriptor_index,
            descriptor_generation=lease.descriptor_generation,
            broker_epoch=lease.broker_epoch,
            offset=lease.offset,
            content_length=lease.content_length,
            allocation_capacity_bytes=lease.allocation_capacity_bytes,
            shape=image.shape,
            dtype=image.dtype,
            layout=image.layout,
            pixel_format=image.pixel_format,
            media_type=image.media_type,
            readonly=True,
        )

    @staticmethod
    def _validate_request_identity(
        pending: _PendingMailboxRequest,
        request: WorkflowTriggerRequestV1,
    ) -> None:
        """REQUEST 不能替换 PREPARE 已固定的 source/event。"""

        if (
            request.trigger_source_id != pending.trigger_source_id
            or request.event_id != pending.event_id
        ):
            raise InvalidRequestError(
                "Workflow Trigger REQUEST 与 PREPARE identity 不匹配"
            )

    def _publish_failure(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        error: Exception,
        *,
        pending: _PendingMailboxRequest | None,
        source_id: str | None = None,
        capacity_error_code: int = (
            mailbox_contract.ERROR_CODE_LOCAL_BUFFER_CAPACITY_EXHAUSTED
        ),
    ) -> None:
        """发布稳定 inline 错误；无法发布时立即结束本 descriptor 的责任。"""

        message = error.message if isinstance(error, ServiceError) else str(error)
        requested_error_code = _map_error_code(
            error,
            capacity_error_code=capacity_error_code,
        )
        published_error_code = requested_error_code
        cleanup_after_record = False
        try:
            published_error_code = self.mailbox.publish_error(
                identity=identity,
                error_code=requested_error_code,
                message=message or type(error).__name__,
            )
        except Exception:
            if pending is not None:
                pending.protocol_terminal = True
                cleanup_after_record = not pending.task_active
        finally:
            with self._pending_lock:
                self._recent_request_error = {
                    "error_type": type(error).__name__,
                    "error_code": getattr(error, "code", "protocol_error"),
                    "published_error_code": _mailbox_error_code_name(
                        published_error_code
                    ),
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
                if pending is None or not pending.outcome_recorded:
                    self._failed_request_count += 1
                    if pending is not None:
                        pending.outcome_recorded = True
                    resolved_source_id = source_id or (
                        pending.trigger_source_id if pending is not None else None
                    )
                    if resolved_source_id is not None:
                        self._record_source_failure_locked(
                            resolved_source_id,
                            error,
                            published_error_code=published_error_code,
                            pending=pending,
                        )
                        self._prune_source_health_locked(resolved_source_id)
        if cleanup_after_record:
            self._cleanup_pending(identity)

    def _raise_if_request_terminal(self, pending: _PendingMailboxRequest) -> None:
        """在每个昂贵阶段前执行同一 cancel/deadline 快速检查。"""

        cancel_event = pending.cancel_event
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelledError("Workflow Trigger request 已取消")
        if monotonic_ns() >= pending.identity.deadline_ns:
            if cancel_event is not None:
                cancel_event.set()
            raise OperationTimeoutError("Workflow Trigger request deadline 已到期")
        cancel_reason = self.mailbox.read_cancel_reason(identity=pending.identity)
        if cancel_reason != mailbox_contract.CANCEL_REASON_NONE:
            if cancel_event is not None:
                cancel_event.set()
            raise OperationCancelledError(
                "Workflow Trigger request 已取消",
                details={"cancel_reason": cancel_reason},
            )

    def _signal_request_cancel(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        protocol_terminal: bool,
    ) -> None:
        """把 mailbox 终止信号传播到唯一 Runtime 调用。"""

        with self._pending_lock:
            pending = self._pending.get(identity)
            if pending is None:
                return
            if pending.cancel_event is not None:
                pending.cancel_event.set()
            if protocol_terminal:
                pending.protocol_terminal = True
            should_cleanup = protocol_terminal and not pending.task_active
        if should_cleanup:
            self._cleanup_pending(identity)

    def _mark_protocol_terminal(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> None:
        """ACK/CANCEL/deadline 回收后结束 source permit 或等待活动 task。"""

        with self._pending_lock:
            pending = self._pending.get(identity)
            if pending is None:
                return
            pending.protocol_terminal = True
            should_cleanup = not pending.task_active
        if should_cleanup:
            self._cleanup_pending(identity)

    def _cleanup_pending(self, identity: WorkflowTriggerDescriptorIdentity) -> None:
        """幂等释放当前 receipt、未消费 permit 和 source permit。"""

        with self._pending_lock:
            pending = self._pending.get(identity)
            if pending is None or pending.cleanup_started:
                return
            pending.cleanup_started = True
        try:
            reclaim_started_at = perf_counter()
            if pending.executor_permit is not None:
                self._run_cleanup_step(
                    identity,
                    step="executor-permit",
                    callback=lambda: self.executor.release_reserved(
                        pending.executor_permit
                    ),
                )
            if pending.admission is not None:
                self._run_cleanup_step(
                    identity,
                    step="runtime-admission",
                    callback=lambda: (
                        self.runtime_service.fail_admitted_sync_workflow_run(
                            pending.admission,
                            error=InvalidRequestError("Workflow Trigger 协议已终止"),
                        )
                    ),
                )
            self._run_cleanup_step(
                identity,
                step="input-lease",
                callback=lambda: self._release_receipt_if_present(pending),
            )
            self._run_cleanup_step(
                identity,
                step="output-leases",
                callback=lambda: self._release_output_receipts(pending),
            )
            self._run_cleanup_step(
                identity,
                step="source-permit",
                callback=lambda: self.routes.release_source_permit(
                    pending.source_permit
                ),
            )
            pending.timings["lease_reclaim_ms"] = _elapsed_ms(reclaim_started_at)
        finally:
            with self._pending_lock:
                if self._pending.get(identity) is pending:
                    self._pending.pop(identity, None)
                self._prune_source_health_locked(pending.trigger_source_id)
                self._latest_timings = dict(pending.timings)

    @staticmethod
    def _run_cleanup_step(
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        step: str,
        callback: Callable[[], object],
    ) -> bool:
        """逐项执行补偿；单项异常不得阻断其余容量和 lease 回收。"""

        try:
            callback()
            return True
        except Exception:
            logger.exception(
                "Workflow Trigger 清理步骤失败",
                extra={
                    "cleanup_step": step,
                    "descriptor_index": identity.descriptor_index,
                    "descriptor_generation": identity.generation,
                },
            )
            return False

    def _record_request_observation(
        self,
        pending: _PendingMailboxRequest,
        *,
        workflow_state: str,
        published_error_code: int,
        workflow_error_code: str | None = None,
    ) -> None:
        """以 SDK 最终可见终态记录完成计数和稳定错误分类。"""

        with self._pending_lock:
            self._latest_timings = dict(pending.timings)
            if pending.outcome_recorded:
                return
            pending.outcome_recorded = True
            source = self._source_health.setdefault(
                pending.trigger_source_id,
                _SourceMailboxHealth(),
            )
            succeeded = (
                workflow_state == "succeeded"
                and published_error_code == mailbox_contract.ERROR_CODE_NONE
            )
            if succeeded:
                self._completed_request_count += 1
                source.success_count += 1
                return

            self._failed_request_count += 1
            source.error_count += 1
            if published_error_code in {
                mailbox_contract.ERROR_CODE_TRIGGER_SOURCE_BUSY,
                mailbox_contract.ERROR_CODE_WORKFLOW_RUNTIME_BUSY,
                mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTOR_BUSY,
            } or workflow_error_code in BUSY_ERROR_CODES:
                source.busy_count += 1
            if published_error_code in {
                mailbox_contract.ERROR_CODE_LOCAL_BUFFER_CAPACITY_EXHAUSTED,
                mailbox_contract.ERROR_CODE_LOCAL_BUFFER_OUTPUT_CAPACITY_EXHAUSTED,
                mailbox_contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED,
            } or workflow_error_code in CAPACITY_ERROR_CODES:
                source.capacity_reject_count += 1
            if (
                workflow_state == "timed_out"
                or published_error_code == mailbox_contract.ERROR_CODE_DEADLINE_EXCEEDED
            ):
                source.timeout_count += 1
            if published_error_code == mailbox_contract.ERROR_CODE_DEADLINE_EXCEEDED:
                source.request_timeout_count += 1
                pending.terminal_categories.add("deadline_exceeded_identities")
            if published_error_code == mailbox_contract.ERROR_CODE_CANCELLED:
                source.cancel_count += 1
                pending.terminal_categories.add("cancelled_identities")
            source.recent_error = {
                "error_type": "WorkflowTriggerPublishedResult",
                "error_code": _mailbox_error_code_name(published_error_code),
                "workflow_error_code": workflow_error_code,
                "workflow_state": workflow_state,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }

    def _prune_source_health_locked(self, trigger_source_id: str) -> None:
        """只为已登记或仍有在途请求的 source 保留 health。"""

        if trigger_source_id in self._registered_source_ids:
            return
        if any(
            item.trigger_source_id == trigger_source_id
            for item in self._pending.values()
        ):
            return
        self._source_health.pop(trigger_source_id, None)

    def _record_source_request(self, trigger_source_id: str) -> None:
        """在 PREPARE 能确定 source identity 后只记录一次请求。"""

        with self._pending_lock:
            source = self._source_health.setdefault(
                trigger_source_id,
                _SourceMailboxHealth(),
            )
            source.last_triggered_at = datetime.now(timezone.utc).isoformat()
            source.request_count += 1

    def _record_source_failure_locked(
        self,
        trigger_source_id: str,
        error: Exception,
        *,
        published_error_code: int,
        pending: _PendingMailboxRequest | None,
    ) -> None:
        """按 SDK 最终可见错误码记录 PREPARE/REQUEST 失败分类。"""

        source = self._source_health.setdefault(
            trigger_source_id,
            _SourceMailboxHealth(),
        )
        source.error_count += 1
        if published_error_code in {
            mailbox_contract.ERROR_CODE_TRIGGER_SOURCE_BUSY,
            mailbox_contract.ERROR_CODE_WORKFLOW_RUNTIME_BUSY,
            mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTOR_BUSY,
        }:
            source.busy_count += 1
        if published_error_code in {
            mailbox_contract.ERROR_CODE_LOCAL_BUFFER_CAPACITY_EXHAUSTED,
            mailbox_contract.ERROR_CODE_LOCAL_BUFFER_OUTPUT_CAPACITY_EXHAUSTED,
            mailbox_contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED,
        }:
            source.capacity_reject_count += 1
        if published_error_code == mailbox_contract.ERROR_CODE_DEADLINE_EXCEEDED:
            source.timeout_count += 1
            source.request_timeout_count += 1
            if pending is not None:
                pending.terminal_categories.add("deadline_exceeded_identities")
        if published_error_code == mailbox_contract.ERROR_CODE_CANCELLED:
            source.cancel_count += 1
            if pending is not None:
                pending.terminal_categories.add("cancelled_identities")
        source.recent_error = {
            "error_type": type(error).__name__,
            "error_code": getattr(error, "code", "protocol_error"),
            "published_error_code": _mailbox_error_code_name(published_error_code),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }

    def _record_terminal_category(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
        *,
        category: str,
    ) -> None:
        """记录 sweep 发现的 request/cancel/ACK terminal，避免重复计数。"""

        with self._pending_lock:
            pending = self._pending.get(identity)
            if pending is None or category in pending.terminal_categories:
                return
            pending.terminal_categories.add(category)
            source = self._source_health.setdefault(
                pending.trigger_source_id,
                _SourceMailboxHealth(),
            )
            if category == "cancelled_identities":
                source.cancel_count += 1
            elif category == "deadline_exceeded_identities":
                source.timeout_count += 1
                source.request_timeout_count += 1
            elif category == "response_ack_timeout_identities":
                source.timeout_count += 1
                source.response_ack_timeout_count += 1
            if (
                category != "response_ack_timeout_identities"
                and not pending.outcome_recorded
            ):
                pending.outcome_recorded = True
                source.error_count += 1
                self._failed_request_count += 1

    def _release_receipt_if_present(self, pending: _PendingMailboxRequest) -> None:
        """条件释放 context 当前 receipt，stale 表示 worker 已完成清理。"""

        receipt = pending.current_receipt
        if receipt is None:
            return
        self._release_receipt(receipt)
        pending.current_receipt = None

    def _release_receipt(self, receipt: LeaseOwnershipReceipt) -> None:
        """按完整 identity release，旧 owner completion 只能 no-op。"""

        try:
            self._require_local_buffer_client().conditional_release(receipt=receipt)
        except ServiceError:
            return

    def _release_output_receipts(self, pending: _PendingMailboxRequest) -> None:
        """ACK、cancel 或 deadline 后统一回收 response owner lease。"""

        receipts = pending.output_receipts
        pending.output_receipts = ()
        for receipt in receipts:
            self._release_receipt(receipt)

    def _require_local_buffer_client(self) -> LocalBufferBrokerClient:
        """返回 supervisor 生命周期内复用的专用 Broker client。"""

        client = self._local_buffer_client
        if client is not None:
            return client
        provider = self._local_buffer_client_provider
        if provider is None:
            raise InvalidRequestError("LocalBufferBroker client provider 不存在")
        client = provider()
        if client is None:
            raise InvalidRequestError("LocalBufferBroker 尚未启动")
        self._local_buffer_client = client
        return client

    def _get_pending(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> _PendingMailboxRequest | None:
        """按完整 descriptor identity 读取 context。"""

        with self._pending_lock:
            return self._pending.get(identity)


def _build_response_owner_id(identity: WorkflowTriggerDescriptorIdentity) -> str:
    """用完整 descriptor identity 隔离迟到 ACK 和槽位复用。"""

    return (
        f"{identity.descriptor_index}:{identity.generation}:"
        f"{identity.owner_token}:{identity.request_id.hex}"
    )


def _map_error_code(
    error: Exception,
    *,
    capacity_error_code: int = (
        mailbox_contract.ERROR_CODE_LOCAL_BUFFER_CAPACITY_EXHAUSTED
    ),
) -> int:
    """把应用错误映射到冻结的 mailbox error code。"""

    if isinstance(error, WorkflowTriggerSourceBusyError):
        return mailbox_contract.ERROR_CODE_TRIGGER_SOURCE_BUSY
    if isinstance(error, WorkflowRuntimeBusyError):
        return mailbox_contract.ERROR_CODE_WORKFLOW_RUNTIME_BUSY
    if isinstance(error, WorkflowTriggerExecutorBusyError):
        return mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTOR_BUSY
    if isinstance(error, LocalBufferCapacityError):
        return capacity_error_code
    if isinstance(error, OperationTimeoutError):
        return mailbox_contract.ERROR_CODE_DEADLINE_EXCEEDED
    if isinstance(error, OperationCancelledError):
        return mailbox_contract.ERROR_CODE_CANCELLED
    if isinstance(error, (ValidationError, InvalidRequestError)):
        return mailbox_contract.ERROR_CODE_INVALID_REQUEST
    if isinstance(error, ServiceError):
        return mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTION_FAILED
    return mailbox_contract.ERROR_CODE_PROTOCOL_ERROR


def _mailbox_error_code_name(error_code: int) -> str:
    """把当前 v1 mailbox 数字错误码转换为稳定诊断名称。"""

    names = {
        mailbox_contract.ERROR_CODE_NONE: "none",
        mailbox_contract.ERROR_CODE_TRIGGER_SOURCE_BUSY: "trigger_source_busy",
        mailbox_contract.ERROR_CODE_WORKFLOW_RUNTIME_BUSY: "workflow_runtime_busy",
        mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTOR_BUSY: "workflow_executor_busy",
        mailbox_contract.ERROR_CODE_LOCAL_BUFFER_CAPACITY_EXHAUSTED: (
            "local_buffer_capacity_exhausted"
        ),
        mailbox_contract.ERROR_CODE_LOCAL_BUFFER_OUTPUT_CAPACITY_EXHAUSTED: (
            "local_buffer_output_capacity_exhausted"
        ),
        mailbox_contract.ERROR_CODE_TRIGGER_RESPONSE_CAPACITY_EXHAUSTED: (
            "trigger_response_capacity_exhausted"
        ),
        mailbox_contract.ERROR_CODE_DEADLINE_EXCEEDED: "deadline_exceeded",
        mailbox_contract.ERROR_CODE_CANCELLED: "cancelled",
        mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTION_FAILED: (
            "workflow_execution_failed"
        ),
        mailbox_contract.ERROR_CODE_OUTPUT_HANDOFF_FAILED: "output_handoff_failed",
        mailbox_contract.ERROR_CODE_PROTOCOL_ERROR: "protocol_error",
    }
    return names.get(error_code, f"mailbox_error_{error_code}")


def _elapsed_ms(started_at: float) -> float:
    """返回非负的毫秒阶段耗时。"""

    return round(max(0.0, perf_counter() - started_at) * 1_000, 3)


def _read_numeric_timings(value: dict[str, object]) -> dict[str, float]:
    """只读取数值 timing，拒绝把业务对象带入 health 或结果诊断。"""

    return {
        str(key): round(max(0.0, float(item)), 3)
        for key, item in value.items()
        if isinstance(item, int | float) and not isinstance(item, bool)
    }


def _merge_result_timings(
    metadata: dict[str, object],
    timings: dict[str, float],
) -> dict[str, object]:
    """把本机共享内存阶段耗时合并到 Trigger Result metadata。"""

    payload = dict(metadata)
    current = payload.get("timings")
    merged = dict(current) if isinstance(current, dict) else {}
    merged.update(timings)
    payload["timings"] = merged
    return payload
