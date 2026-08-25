"""全局 Workflow Trigger mailbox 的路由、准入、handoff 与执行监督器。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import logging
from pathlib import Path
from threading import Event, Lock, Thread
from time import perf_counter, sleep
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
    WorkflowTriggerPrepareV1,
    WorkflowTriggerRequestV1,
)
from backend.service.application.errors import (
    InvalidRequestError,
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
from backend.service.infrastructure.ipc.workflow_trigger_mailbox import (
    WorkflowTriggerDescriptorIdentity,
    WorkflowTriggerMailboxRequest,
    WorkflowTriggerMailboxServer,
)


logger = logging.getLogger(__name__)


@dataclass
class _PendingMailboxRequest:
    """保存 descriptor 外部的权威路由、permit 和 private receipt。"""

    identity: WorkflowTriggerDescriptorIdentity
    prepare: WorkflowTriggerPrepareV1
    route: WorkflowTriggerRoute
    source_permit: WorkflowTriggerSourcePermit
    allocation: ExternalBufferAllocation | None = None
    current_receipt: LeaseOwnershipReceipt | None = None
    trigger_event: TriggerEventContract | None = None
    admission: WorkflowRuntimeSyncAdmission | None = None
    executor_permit: WorkflowTriggerExecutorPermit | None = None
    task_active: bool = False
    protocol_terminal: bool = False
    output_receipts: tuple[LeaseOwnershipReceipt, ...] = ()
    started_at: float = field(default_factory=perf_counter)
    writing_published_at: float | None = None
    executor_submitted_at: float | None = None
    timings: dict[str, float] = field(default_factory=dict)


class WorkflowTriggerMailboxSupervisor:
    """持有单 mailbox owner，并把 poller 与 Workflow 执行严格解耦。"""

    def __init__(
        self,
        *,
        buffers_root: str | Path,
        runtime_service: WorkflowRuntimeService,
        local_buffer_client: LocalBufferBrokerClient | None = None,
        local_buffer_client_provider: (
            Callable[[], LocalBufferBrokerClient | None] | None
        ) = None,
        max_executor_workers: int,
        poll_interval_seconds: float = 0.001,
    ) -> None:
        """初始化全局 mailbox、route registry 和无隐藏队列 executor。"""

        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        if local_buffer_client is None and local_buffer_client_provider is None:
            raise ValueError(
                "local_buffer_client 与 local_buffer_client_provider 至少提供一个"
            )
        self.buffers_root = Path(buffers_root)
        self.runtime_service = runtime_service
        self._local_buffer_client = local_buffer_client
        self._local_buffer_client_provider = local_buffer_client_provider
        self._owns_local_buffer_client = local_buffer_client is None
        self._mailbox: WorkflowTriggerMailboxServer | None = None
        self.routes = WorkflowTriggerRouteRegistry()
        self.executor = BoundedWorkflowTriggerExecutor(
            max_workers=max_executor_workers
        )
        self.input_binding_mapper = InputBindingMapper()
        self.result_dispatcher = WorkflowResultDispatcher()
        self.poll_interval_seconds = poll_interval_seconds
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
        self._idle_poll_sleep_count = 0
        self._orphan_sweep_cursor = 0
        self._stop_event = Event()
        self._thread: Thread | None = None

    @property
    def mailbox(self) -> WorkflowTriggerMailboxServer:
        """返回惰性创建的唯一 mailbox owner。"""

        mailbox = self._mailbox
        if mailbox is None:
            mailbox = WorkflowTriggerMailboxServer(buffers_root=self.buffers_root)
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
        return self.routes.register(trigger_source)

    def unregister_trigger_source(self, trigger_source_id: str) -> None:
        """停止一条 source 的新 PREPARE，不中断已有请求。"""

        self.routes.unregister(trigger_source_id)

    def start(self) -> None:
        """启动唯一 poller；重复调用保持幂等。"""

        if self._thread is not None and self._thread.is_alive():
            return
        self._require_local_buffer_client()
        self.mailbox
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
            "idle_poll_sleep_count": idle_poll_sleep_count,
            "latest_timings": latest_timings,
        }

    def close(self) -> None:
        """停止 poller，等待正式任务结束，并按 receipt 清理全部上下文。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self.executor.shutdown(wait=True, cancel_futures=False)
        with self._pending_lock:
            identities = tuple(self._pending)
        for identity in identities:
            self._cleanup_pending(identity)
        mailbox = self._mailbox
        self._mailbox = None
        if mailbox is not None:
            mailbox.close()
        client = self._local_buffer_client
        self._local_buffer_client = None
        if self._owns_local_buffer_client and client is not None:
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
        prepare_started_at = perf_counter()
        try:
            prepare_decode_started_at = perf_counter()
            prepare = WorkflowTriggerPrepareV1.model_validate_json(payload)
            route = self.routes.get_route(
                trigger_source_id=prepare.trigger_source_id,
                expected_generation=route_generation,
            )
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
                size=prepare.image.content_length,
                owner_kind="workflow-trigger-write",
                owner_id=(
                    f"{prepare.trigger_source_id}:{identity.request_id.hex}"
                ),
                deadline_ns=identity.deadline_ns,
                pool_name=_read_optional_pool_name(route.trigger_source),
                trace_id=prepare.event_id,
            )
            pending.timings["broker_allocate_ms"] = _elapsed_ms(
                broker_allocate_started_at
            )
            pending.allocation = allocation
            pending.current_receipt = allocation.receipt
            allocation_contract = WorkflowTriggerAllocationV1(
                pool_name=allocation.lease.pool_name,
                lease_id=allocation.lease.lease_id,
                buffer_id=allocation.lease.buffer_id,
                path=allocation.lease.file_path,
                offset=allocation.lease.offset,
                size=allocation.lease.size,
                slot_capacity_bytes=allocation.slot_capacity_bytes,
                broker_epoch=allocation.lease.broker_epoch,
                generation=allocation.lease.generation,
                writer_guard_path=allocation.receipt.writer_guard_path,
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
            pending.timings["mailbox_prepare_ms"] = _elapsed_ms(
                prepare_started_at
            )
            pending.writing_published_at = perf_counter()
        except Exception as error:
            if pending is not None and pending.current_receipt is not None:
                self._release_receipt(pending.current_receipt)
                pending.current_receipt = None
            self._publish_failure(identity, error, pending=pending)

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
            pending.timings["request_decode_validate_ms"] = _elapsed_ms(
                request_decode_started_at
            )
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
            admission = self.runtime_service.admit_sync_workflow_run(
                pending.route.trigger_source.workflow_runtime_id,
                WorkflowRuntimeInvokeRequest(
                    input_bindings=input_bindings,
                    execution_metadata=build_trigger_execution_metadata(
                        submit_request
                    ),
                    timeout_seconds=(
                        pending.route.trigger_source.reply_timeout_seconds
                    ),
                ),
                created_by=pending.route.trigger_source.created_by,
                execution_acquisition_mode="reject",
            )
            pending.timings["runtime_admission_ms"] = _elapsed_ms(
                runtime_admission_started_at
            )
            pending.admission = admission
            executor_reserve_started_at = perf_counter()
            executor_permit = self.executor.reserve()
            pending.timings["executor_reserve_ms"] = _elapsed_ms(
                executor_reserve_started_at
            )
            pending.executor_permit = executor_permit
            commit_handoff_started_at = perf_counter()
            committed = self._require_local_buffer_client().publish_and_transfer_external_buffer(
                receipt=pending.current_receipt,
                media_type=pending.prepare.image.media_type,
                new_owner_kind="workflow-runtime",
                new_owner_id=(
                    f"{admission.workflow_run.workflow_run_id}:"
                    f"{admission.workflow_app_runtime.workflow_runtime_id}:"
                    f"{request.identity.request_id.hex}"
                ),
                deadline_ns=request.identity.deadline_ns,
                shape=pending.prepare.image.shape,
                dtype=pending.prepare.image.dtype,
                layout=pending.prepare.image.layout,
                pixel_format=pending.prepare.image.pixel_format,
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
                pool_name=runtime_receipt.pool_name,
                ownership_receipt=runtime_receipt,
            )
            admission = replace(admission, execution_metadata=execution_metadata)
            pending.admission = admission
            pending.task_active = True
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

    def _execute_pending(self, identity: WorkflowTriggerDescriptorIdentity) -> None:
        """在有界 worker 中执行 Workflow；完成后只发布结果，不在 poller 等待。"""

        pending = self._get_pending(identity)
        if pending is None or pending.admission is None or pending.trigger_event is None:
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
            mailbox_publish_response_started_at = perf_counter()
            self.mailbox.publish_response(
                identity=identity,
                payload=response_payload,
                error_code=error_code,
                response_output_lease_count=len(pending.output_receipts),
                handoff_state=(
                    mailbox_contract.HANDOFF_STATE_COMPLETE
                    if pending.output_receipts
                    else mailbox_contract.HANDOFF_STATE_NONE
                ),
            )
            pending.timings["mailbox_publish_response_ms"] = _elapsed_ms(
                mailbox_publish_response_started_at
            )
            self._record_request_observation(
                pending,
                failed=trigger_result.state != "succeeded",
            )
        except Exception as error:
            self._publish_failure(identity, error, pending=pending)
        finally:
            pending.task_active = False
            pending.executor_permit = None
            self._release_receipt_if_present(pending)
            if pending.protocol_terminal:
                self._cleanup_pending(identity)

    def _compensate_before_worker_submit(
        self,
        pending: _PendingMailboxRequest,
        error: Exception,
    ) -> None:
        """按当前权威 receipt 逆序补偿 executor、Runtime 和 LocalBuffer。"""

        if pending.executor_permit is not None:
            self.executor.release_reserved(pending.executor_permit)
            pending.executor_permit = None
        if pending.admission is not None:
            self.runtime_service.fail_admitted_sync_workflow_run(
                pending.admission,
                error=error,
            )
            pending.admission = None
        self._release_receipt_if_present(pending)

    def _build_trigger_event(
        self,
        pending: _PendingMailboxRequest,
        request: WorkflowTriggerRequestV1,
        buffer_ref: BufferRef,
    ) -> TriggerEventContract:
        """把 committed BufferRef 放入受 route mapping 约束的事件 payload。"""

        event_payload = dict(request.payload)
        event_payload[pending.prepare.image.event_payload_key] = {
            "transport_kind": "buffer",
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
        image = pending.prepare.image
        return BufferRef(
            buffer_id=lease.buffer_id,
            lease_id=lease.lease_id,
            path=lease.file_path,
            offset=lease.offset,
            size=lease.size,
            shape=image.shape,
            dtype=image.dtype,
            layout=image.layout,
            pixel_format=image.pixel_format,
            media_type=image.media_type,
            readonly=True,
            broker_epoch=lease.broker_epoch,
            generation=lease.generation,
        )

    @staticmethod
    def _validate_request_identity(
        pending: _PendingMailboxRequest,
        request: WorkflowTriggerRequestV1,
    ) -> None:
        """REQUEST 不能替换 PREPARE 已固定的 source/event。"""

        if (
            request.trigger_source_id != pending.prepare.trigger_source_id
            or request.event_id != pending.prepare.event_id
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
    ) -> None:
        """发布稳定 inline 错误；无法发布时立即结束本 descriptor 的责任。"""

        message = error.message if isinstance(error, ServiceError) else str(error)
        with self._pending_lock:
            self._recent_request_error = {
                "error_type": type(error).__name__,
                "error_code": getattr(error, "code", "protocol_error"),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            self._failed_request_count += 1
        try:
            self.mailbox.publish_error(
                identity=identity,
                error_code=_map_error_code(error),
                message=message or type(error).__name__,
            )
        except Exception:
            if pending is not None:
                pending.protocol_terminal = True
                if not pending.task_active:
                    self._cleanup_pending(identity)

    def _mark_protocol_terminal(
        self,
        identity: WorkflowTriggerDescriptorIdentity,
    ) -> None:
        """ACK/CANCEL/deadline 回收后结束 source permit 或等待活动 task。"""

        pending = self._get_pending(identity)
        if pending is None:
            return
        pending.protocol_terminal = True
        if not pending.task_active:
            self._cleanup_pending(identity)

    def _cleanup_pending(self, identity: WorkflowTriggerDescriptorIdentity) -> None:
        """幂等释放当前 receipt、未消费 permit 和 source permit。"""

        with self._pending_lock:
            pending = self._pending.pop(identity, None)
        if pending is None:
            return
        reclaim_started_at = perf_counter()
        if pending.executor_permit is not None:
            self.executor.release_reserved(pending.executor_permit)
        if pending.admission is not None:
            self.runtime_service.fail_admitted_sync_workflow_run(
                pending.admission,
                error=InvalidRequestError("Workflow Trigger 协议已终止"),
            )
        self._release_receipt_if_present(pending)
        self._release_output_receipts(pending)
        self.routes.release_source_permit(pending.source_permit)
        pending.timings["lease_reclaim_ms"] = _elapsed_ms(reclaim_started_at)
        with self._pending_lock:
            self._latest_timings = dict(pending.timings)

    def _record_request_observation(
        self,
        pending: _PendingMailboxRequest,
        *,
        failed: bool,
    ) -> None:
        """记录不含请求内容的完成计数和最近阶段耗时。"""

        with self._pending_lock:
            self._latest_timings = dict(pending.timings)
            if failed:
                self._failed_request_count += 1
            else:
                self._completed_request_count += 1

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

def _read_optional_pool_name(trigger_source: WorkflowTriggerSource) -> str | None:
    """读取 source 固定的可选 LocalBuffer pool。"""

    value = trigger_source.transport_config.get("pool_name")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _build_response_owner_id(identity: WorkflowTriggerDescriptorIdentity) -> str:
    """用完整 descriptor identity 隔离迟到 ACK 和槽位复用。"""

    return (
        f"{identity.descriptor_index}:{identity.generation}:"
        f"{identity.owner_token}:{identity.request_id.hex}"
    )


def _map_error_code(error: Exception) -> int:
    """把应用错误映射到冻结的 mailbox error code。"""

    if isinstance(error, WorkflowTriggerSourceBusyError):
        return mailbox_contract.ERROR_CODE_TRIGGER_SOURCE_BUSY
    if isinstance(error, WorkflowRuntimeBusyError):
        return mailbox_contract.ERROR_CODE_WORKFLOW_RUNTIME_BUSY
    if isinstance(error, WorkflowTriggerExecutorBusyError):
        return mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTOR_BUSY
    if isinstance(error, (ValidationError, InvalidRequestError)):
        return mailbox_contract.ERROR_CODE_INVALID_REQUEST
    if isinstance(error, ServiceError):
        return mailbox_contract.ERROR_CODE_WORKFLOW_EXECUTION_FAILED
    return mailbox_contract.ERROR_CODE_PROTOCOL_ERROR


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
