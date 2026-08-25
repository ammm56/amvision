"""ZeroMQ TriggerSource adapter。"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from threading import Event, RLock, Thread
from time import perf_counter
from collections.abc import Callable
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.buffers import BufferRef
from backend.contracts.buffers.lease_ownership import LeaseOwnershipReceipt
from backend.contracts.workflows import TriggerResultContract
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.images.image_matrix import (
    IMAGE_MEDIA_TYPE_RAW,
    validate_raw_bgr24_bytes,
)
from backend.service.application.runtime.support.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)
from backend.service.application.workflows.trigger_sources.protocol_adapter import (
    WorkflowTriggerDispatchResult,
    WorkflowTriggerEventHandler,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    PreparedPhysicalPayload,
    PreparedTriggerResult,
    list_prepared_result_ownership_receipts,
)
from backend.service.application.workflows.trigger_sources.zeromq_transport import (
    ZeroMqTriggerRuntimeConfig,
)
from backend.service.application.workflows.runtime.policies import (
    should_return_workflow_timing_metadata,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY,
    build_local_buffer_lease_cleanup_item,
)
from backend.service.application.workflows.trigger_sources.trigger_event_normalizer import (
    RawTriggerEvent,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.integrations.zeromq.zeromq_transport_lifetime import (
    ZeroMqTransportLifetimeRegistry,
    ZeroMqTransportReservation,
)


class LocalBufferByteWriter(Protocol):
    """定义 ZeroMQ adapter 写入 LocalBufferBroker 所需的最小接口。"""

    def write_bytes(
        self,
        *,
        content: bytes,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        pool_name: str | None = None,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> object:
        """写入 bytes 并返回带 buffer_ref 属性的结果对象。"""

        ...

    def release(self, lease_id: str, *, pool_name: str | None = None) -> None:
        """释放指定 LocalBufferBroker lease。"""

        ...

    def acquire_buffer_reader_guard(
        self,
        *,
        buffer_ref: BufferRef,
        deadline_ns: int,
    ) -> AbstractContextManager[None]:
        """持有发送期间的跨进程 reader guard。"""

        ...

    def read_buffer_ref_view(self, buffer_ref: BufferRef) -> memoryview:
        """读取经过 identity 校验的只读 mmap view。"""

        ...

    def conditional_release(self, *, receipt: LeaseOwnershipReceipt) -> str:
        """按完整 receipt fence 释放 output lease。"""

        ...


class ZeroMqFrameEnvelope(BaseModel):
    """描述 ZeroMQ multipart 第一帧 JSON envelope。

    字段：
    - trigger_source_id：可选 TriggerSource id，用于校验消息目标。
    - event_id：外部事件 id。
    - trace_id：链路追踪 id。
    - occurred_at：事件发生时间。
    - input_binding：图片 bytes 写入 payload 后对应的字段名。
    - media_type：图片或 frame 媒体类型。
    - shape：raw 图像或 tensor 形状。
    - dtype：raw 数据类型。
    - layout：raw 数据布局。
    - pixel_format：像素格式。
    - metadata：附加事件元数据。
    - payload：附加业务 payload。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_source_id: str | None = None
    event_id: str | None = None
    trace_id: str | None = None
    occurred_at: str | None = None
    input_binding: str | None = None
    media_type: str | None = None
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    payload: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_envelope(self) -> ZeroMqFrameEnvelope:
        """校验 envelope 字段。"""

        if self.trigger_source_id is not None:
            _require_stripped_text(self.trigger_source_id, "trigger_source_id")
        if self.event_id is not None:
            _require_stripped_text(self.event_id, "event_id")
        if self.trace_id is not None:
            _require_stripped_text(self.trace_id, "trace_id")
        if self.occurred_at is not None:
            _require_stripped_text(self.occurred_at, "occurred_at")
        if self.input_binding is not None:
            _require_stripped_text(self.input_binding, "input_binding")
        if self.media_type is not None:
            _require_stripped_text(self.media_type, "media_type")
        if any(dimension <= 0 for dimension in self.shape):
            raise ValueError("shape 中的维度必须为正整数")
        return self


@dataclass
class _ZeroMqAdapterState:
    """描述一个 ZeroMQ TriggerSource 的 adapter 运行状态。

    字段：
    - trigger_source_id：触发源 id。
    - bind_endpoint：ZeroMQ bind endpoint。
    - stop_event：线程停止信号。
    - startup_event：线程启动结果信号。
    - thread：后台监听线程。
    - running：socket 是否已经进入轮询循环。
    - received_count：收到的 multipart 消息数量。
    - submitted_count：已提交到 event handler 的消息数量。
    - error_count：失败消息数量。
    - timeout_count：超时消息数量。
    - last_error：最近错误消息。
    - startup_error：启动阶段错误消息。
    """

    trigger_source_id: str
    bind_endpoint: str
    stop_event: Event
    socket_generation: str = field(
        default_factory=lambda: f"zeromq-socket-{uuid4().hex}"
    )
    startup_event: Event = field(default_factory=Event)
    stopped_event: Event = field(default_factory=Event)
    lifecycle_lock: RLock = field(default_factory=RLock)
    thread: Thread | None = None
    running: bool = False
    stopping: bool = False
    received_count: SafeCounterState = field(default_factory=SafeCounterState)
    submitted_count: SafeCounterState = field(default_factory=SafeCounterState)
    error_count: SafeCounterState = field(default_factory=SafeCounterState)
    timeout_count: SafeCounterState = field(default_factory=SafeCounterState)
    last_error: str | None = None
    startup_error: str | None = None


@dataclass
class _PreparedZeroMqReply:
    """保存一次尚未交给 libzmq 的零复制 multipart reply。"""

    frames: list[object]
    reservation: ZeroMqTransportReservation
    cleanup: Callable[[], None]


@dataclass(frozen=True)
class _FrameTrackerGroup:
    """把每个物理图片 frame 的 tracker 合并为单个只读状态。"""

    trackers: tuple[object, ...]

    @property
    def done(self) -> bool:
        """仅当全部物理 frame 都不再被 libzmq 借用时返回 True。"""

        return all(bool(getattr(tracker, "done", False)) for tracker in self.trackers)


class ZeroMqTriggerAdapter:
    """把 ZeroMQ multipart 消息转换为 TriggerSource 原始事件。"""

    adapter_kind = "zeromq-topic"

    def __init__(
        self,
        *,
        local_buffer_writer: LocalBufferByteWriter,
        runtime_config: ZeroMqTriggerRuntimeConfig,
    ) -> None:
        """初始化 ZeroMqTriggerAdapter。

        参数：
        - local_buffer_writer：LocalBufferBroker 写入接口。
        - runtime_config：从 backend-service 统一配置注入的 ZeroMQ 运行参数。
        """

        self.local_buffer_writer = local_buffer_writer
        self.runtime_config = runtime_config
        self._states: dict[str, _ZeroMqAdapterState] = {}
        self._lock = RLock()
        self._transport_timing_lock = RLock()
        self._transport_timings: dict[str, float] = {}
        self._transport_registry = ZeroMqTransportLifetimeRegistry(
            max_entries=runtime_config.transport_registry_max_entries,
            max_bytes=runtime_config.transport_registry_max_bytes,
            tracker_timeout_seconds=runtime_config.transport_tracker_timeout_seconds,
            reaper_poll_interval_seconds=(
                runtime_config.transport_reaper_poll_interval_seconds
            ),
        )

    def start(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
    ) -> None:
        """启动一个 TriggerSource 的 ZeroMQ REP 监听。"""

        bind_endpoint = _read_required_transport_text(trigger_source, "bind_endpoint")
        stop_event = Event()
        state = _ZeroMqAdapterState(
            trigger_source_id=trigger_source.trigger_source_id,
            bind_endpoint=bind_endpoint,
            stop_event=stop_event,
        )
        with self._lock:
            if trigger_source.trigger_source_id in self._states:
                raise InvalidRequestError(
                    "ZeroMQ TriggerSource 已经启动",
                    details={"trigger_source_id": trigger_source.trigger_source_id},
                )
            self._states[trigger_source.trigger_source_id] = state
        thread = Thread(
            target=self._serve_trigger_source,
            args=(trigger_source, event_handler, state),
            name=f"zeromq-trigger-{trigger_source.trigger_source_id}",
            daemon=True,
        )
        state.thread = thread
        thread.start()
        if not state.startup_event.wait(
            timeout=self.runtime_config.startup_timeout_seconds
        ):
            self.stop(trigger_source_id=trigger_source.trigger_source_id)
            raise OperationTimeoutError(
                "等待 ZeroMQ TriggerSource 启动超时",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "timeout_seconds": self.runtime_config.startup_timeout_seconds,
                },
            )
        with state.lifecycle_lock:
            running = state.running
            startup_error = state.startup_error or state.last_error
        if not running:
            with self._lock:
                if state.stopped_event.is_set():
                    self._states.pop(trigger_source.trigger_source_id, None)
            raise ServiceConfigurationError(
                "ZeroMQ TriggerSource 启动失败",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "bind_endpoint": bind_endpoint,
                    "error": startup_error,
                },
            )

    def stop(self, *, trigger_source_id: str) -> None:
        """停止一个 TriggerSource 的 ZeroMQ 监听。"""

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._lock:
            state = self._states.get(normalized_trigger_source_id)
        if state is None:
            return
        with state.lifecycle_lock:
            state.stopping = True
            state.stop_event.set()
        if not state.stopped_event.wait(
            timeout=self.runtime_config.shutdown_timeout_seconds
        ):
            raise OperationTimeoutError(
                "等待 ZeroMQ TriggerSource 停止超时",
                details={
                    "trigger_source_id": normalized_trigger_source_id,
                    "timeout_seconds": self.runtime_config.shutdown_timeout_seconds,
                },
            )
        if state.thread is not None:
            state.thread.join(timeout=0.1)
        with self._lock:
            if self._states.get(normalized_trigger_source_id) is state:
                self._states.pop(normalized_trigger_source_id, None)

    def get_health(self, *, trigger_source_id: str) -> dict[str, object]:
        """读取一个 TriggerSource 的 ZeroMQ adapter health。"""

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._lock:
            state = self._states.get(normalized_trigger_source_id)
        if state is None:
            return {
                "adapter_kind": self.adapter_kind,
                "running": False,
                "trigger_source_id": normalized_trigger_source_id,
            }
        with state.lifecycle_lock:
            running = state.running
            stopping = state.stopping
            last_error = state.last_error
        with self._transport_timing_lock:
            transport_timings = dict(self._transport_timings)
        return {
            "adapter_kind": self.adapter_kind,
            "running": running,
            "stopping": stopping,
            "trigger_source_id": normalized_trigger_source_id,
            "bind_endpoint": state.bind_endpoint,
            "last_error": last_error,
            **_counter_fields("received_count", state.received_count),
            **_counter_fields("submitted_count", state.submitted_count),
            **_counter_fields("error_count", state.error_count),
            **_counter_fields("timeout_count", state.timeout_count),
            **self._transport_registry.snapshot(),
            "transport_timings": transport_timings,
        }

    def handle_multipart_message(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        frames: list[bytes],
        event_handler: WorkflowTriggerEventHandler,
        receive_ms: float | None = None,
    ) -> WorkflowTriggerDispatchResult:
        """处理一条 ZeroMQ multipart 消息。

        参数：
        - trigger_source：消息绑定的 TriggerSource。
        - frames：ZeroMQ multipart 帧列表。
        - event_handler：TriggerSource 事件处理器。

        返回：
        - WorkflowTriggerDispatchResult：公开结果与进程内 output receipt。
        """

        state = self._states.get(trigger_source.trigger_source_id)
        buffer_ref_payload: dict[str, object] | None = None
        adapter_started_at = perf_counter()
        timings: dict[str, object] = {}
        if receive_ms is not None:
            timings["zeromq_receive_ms"] = receive_ms
        if state is not None:
            increment_safe_counter(state.received_count)
        try:
            _validate_multipart_frames(
                frames,
                runtime_config=self.runtime_config,
            )
            parse_started_at = perf_counter()
            envelope = _parse_envelope(frames)
            _validate_envelope_target(trigger_source, envelope)
            timings["zeromq_parse_envelope_ms"] = _elapsed_ms(parse_started_at)
            payload = dict(envelope.payload)
            content = _read_content_frame(frames)
            if content is not None:
                input_binding = _resolve_input_binding(trigger_source, envelope)
                write_started_at = perf_counter()
                buffer_ref_payload = self._write_content_to_buffer(
                    trigger_source=trigger_source,
                    envelope=envelope,
                    content=content,
                )
                timings["zeromq_write_buffer_ms"] = _elapsed_ms(write_started_at)
                payload[input_binding] = {
                    "transport_kind": "buffer",
                    "buffer_ref": buffer_ref_payload,
                }
            metadata = dict(envelope.metadata)
            metadata.setdefault("transport", "zeromq")
            metadata.setdefault("zeromq_frame_count", len(frames))
            event_trigger_source = trigger_source
            if buffer_ref_payload is not None:
                buffer_ref = BufferRef.model_validate(buffer_ref_payload)
                cleanup_item = build_local_buffer_lease_cleanup_item(
                    lease_id=buffer_ref.lease_id,
                    pool_name=_read_optional_transport_text(
                        trigger_source, "pool_name"
                    ),
                )
                execution_metadata = dict(trigger_source.default_execution_metadata)
                execution_metadata[WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY] = (
                    [cleanup_item] if cleanup_item is not None else []
                )
                # 每个事件使用独立的 TriggerSource 副本，把输入 lease cleanup
                # 交给对应 Workflow Run；不修改持久化配置或共享实例。
                event_trigger_source = replace(
                    trigger_source,
                    default_execution_metadata=execution_metadata,
                )
            raw_event = RawTriggerEvent(
                payload=payload,
                event_id=envelope.event_id,
                trace_id=envelope.trace_id,
                occurred_at=envelope.occurred_at,
                metadata=metadata,
            )
            submit_started_at = perf_counter()
            dispatch_result = event_handler.handle_trigger_event(
                trigger_source=event_trigger_source, raw_event=raw_event
            )
            timings["zeromq_submit_event_ms"] = _elapsed_ms(submit_started_at)
            timings["zeromq_adapter_total_ms"] = _elapsed_ms(adapter_started_at)
            if should_return_workflow_timing_metadata(
                trigger_source.default_execution_metadata
            ):
                dispatch_result = replace(
                    dispatch_result,
                    trigger_result=dispatch_result.trigger_result.model_copy(
                        update={
                            "metadata": _merge_trigger_result_timings(
                                dispatch_result.metadata, timings
                            )
                        }
                    ),
                )
            if buffer_ref_payload is not None and (
                dispatch_result.workflow_run_id is None
                or dispatch_result.metadata.get("idempotent_replay") is True
                or dispatch_result.metadata.get("debounced") is True
            ):
                # 没有新建 WorkflowRun 的重复、去抖或提交失败请求不会进入
                # worker cleanup，必须由 adapter 立即释放本次新写入的输入 lease。
                self._release_buffer_ref_payload(buffer_ref_payload)
            if state is not None:
                self._record_result(state, dispatch_result.trigger_result)
            return dispatch_result
        except Exception as error:
            self._release_buffer_ref_payload(buffer_ref_payload)
            if state is not None:
                _record_adapter_error(state, error)
            raise

    def build_reply_frames(
        self, dispatch_result: WorkflowTriggerDispatchResult
    ) -> list[bytes]:
        """把不含图片附件的 TriggerResultContract 转换为 JSON reply。"""

        prepared = dispatch_result.prepared_trigger_result
        if prepared is not None and prepared.physical_payloads:
            raise InvalidRequestError("图片结果必须通过 tracked ZeroMQ multipart 发送")

        return [
            _to_json_bytes(dispatch_result.trigger_result.model_dump(mode="json"))
        ]

    def build_error_reply_frames(
        self,
        *,
        trigger_source_id: str,
        error: Exception,
    ) -> list[bytes]:
        """把异常转换为 ZeroMQ 错误 reply 帧。"""

        error_code = error.code if isinstance(error, ServiceError) else "internal_error"
        error_message = (
            error.message if isinstance(error, ServiceError) else error.__class__.__name__
        )
        details = dict(error.details) if isinstance(error, ServiceError) else {}
        result = TriggerResultContract(
            trigger_source_id=trigger_source_id,
            event_id=f"trigger-error-{uuid4().hex}",
            state="failed",
            error_message=error_message,
            metadata={"error_code": error_code, "error_details": details},
        )
        return [_to_json_bytes(result.model_dump(mode="json"))]

    def _send_dispatch_result(
        self,
        *,
        socket: Any,
        zeromq: Any,
        dispatch_result: WorkflowTriggerDispatchResult,
        socket_generation: str,
    ) -> None:
        """发送 JSON-only 或带去重图片 frame 的统一 Result v1。"""

        prepared_result = dispatch_result.prepared_trigger_result
        if prepared_result is None or not prepared_result.physical_payloads:
            manifest = dispatch_result.trigger_result.model_dump(mode="json")
            manifest_bytes = self._serialize_result_manifest(manifest)
            send_started_at = perf_counter()
            try:
                socket.send_multipart([manifest_bytes])
            finally:
                self._record_transport_timing(
                    "zeromq_attachment_send_ms", _elapsed_ms(send_started_at)
                )
            return
        prepared_reply = self._prepare_tracked_reply(
            zeromq=zeromq,
            dispatch_result=dispatch_result,
            prepared_result=prepared_result,
            socket_generation=socket_generation,
        )
        accepted_trackers: list[object] = []
        send_started_at = perf_counter()
        try:
            socket.send(prepared_reply.frames[0], flags=zeromq.SNDMORE)
            image_frames = prepared_reply.frames[1:]
            for index, frame in enumerate(image_frames):
                flags = zeromq.SNDMORE if index < len(image_frames) - 1 else 0
                send_tracker = socket.send(
                    frame,
                    flags=flags,
                    copy=False,
                    track=True,
                )
                tracker = send_tracker or getattr(frame, "tracker", None)
                if tracker is None:
                    raise ServiceConfigurationError(
                        "ZeroMQ 图片 frame 提交后缺少 MessageTracker"
                    )
                accepted_trackers.append(tracker)
        except Exception:
            # 先关闭 socket，让 libzmq 放弃未发送队列。只把已经被 send 接受的
            # 图片 tracker 交给 reaper；尚未提交的 Frame 销毁后可立即清理。
            socket.close(linger=0)
            prepared_reply.frames.clear()
            if accepted_trackers:
                self._transport_registry.activate(
                    reservation=prepared_reply.reservation,
                    tracker=_FrameTrackerGroup(trackers=tuple(accepted_trackers)),
                    cleanup=prepared_reply.cleanup,
                )
            else:
                self._transport_registry.cancel(
                    reservation=prepared_reply.reservation,
                    cleanup=prepared_reply.cleanup,
                )
            self._record_transport_timing(
                "zeromq_attachment_send_ms", _elapsed_ms(send_started_at)
            )
            raise
        prepared_reply.frames.clear()
        self._record_transport_timing(
            "zeromq_attachment_send_ms", _elapsed_ms(send_started_at)
        )
        self._transport_registry.activate(
            reservation=prepared_reply.reservation,
            tracker=_FrameTrackerGroup(trackers=tuple(accepted_trackers)),
            cleanup=prepared_reply.cleanup,
        )

    def _prepare_tracked_reply(
        self,
        *,
        zeromq: Any,
        dispatch_result: WorkflowTriggerDispatchResult,
        prepared_result: PreparedTriggerResult,
        socket_generation: str,
    ) -> _PreparedZeroMqReply:
        """预留容量、持有 reader guard，并构造零复制物理图片帧。"""

        physical_payloads = tuple(prepared_result.physical_payloads)
        reservation: ZeroMqTransportReservation | None = None
        guard_contexts: list[AbstractContextManager[None]] = []
        views: list[memoryview] = []
        image_frames: list[object] = []
        receipts = list_prepared_result_ownership_receipts(prepared_result)
        cleanup = self._build_output_cleanup(
            guard_contexts=guard_contexts,
            views=views,
            receipts=receipts,
        )
        try:
            if any(item.delivery_kind != "local-buffer" for item in physical_payloads):
                raise InvalidRequestError(
                    "ZeroMQ multipart 图片结果必须先固定到 LocalBuffer"
                )
            payload_bytes = sum(item.content_length for item in physical_payloads)
            reservation = self._transport_registry.reserve(
                payload_bytes=payload_bytes,
                frame_count=len(physical_payloads) + 1,
                socket_generation=socket_generation,
            )
            frame_indexes: dict[str, int] = {}
            for frame_index, item in enumerate(physical_payloads, start=1):
                frame_indexes[item.payload_id] = frame_index
                buffer_ref = BufferRef.model_validate(item.buffer_ref)
                receipt = LeaseOwnershipReceipt.model_validate(item.ownership_receipt)
                guard = self.local_buffer_writer.acquire_buffer_reader_guard(
                    buffer_ref=buffer_ref,
                    deadline_ns=receipt.deadline_ns,
                )
                guard.__enter__()
                guard_contexts.append(guard)
                view = self.local_buffer_writer.read_buffer_ref_view(buffer_ref)
                if len(view) != item.content_length:
                    raise InvalidRequestError(
                        "ZeroMQ 图片结果长度与固定 payload 不一致",
                        details={
                            "payload_id": item.payload_id,
                            "expected_size": item.content_length,
                            "actual_size": len(view),
                        },
                    )
                if len(view) > self.runtime_config.max_message_size_bytes:
                    raise InvalidRequestError(
                        "ZeroMQ 图片结果超过单 frame 大小限制",
                        details={
                            "payload_id": item.payload_id,
                            "max_message_size_bytes": (
                                self.runtime_config.max_message_size_bytes
                            ),
                            "actual_size": len(view),
                        },
                    )
                views.append(view)
                image_frames.append(zeromq.Frame(view, copy=False, track=True))
            manifest = _build_zeromq_result_manifest(
                dispatch_result=dispatch_result,
                prepared_result=prepared_result,
                frame_indexes=frame_indexes,
            )
            manifest_bytes = self._serialize_result_manifest(manifest)
            if len(manifest_bytes) > self.runtime_config.max_message_size_bytes:
                raise InvalidRequestError("ZeroMQ Result manifest 超过单 frame 大小限制")
            trackers = tuple(
                tracker
                for frame in image_frames
                if (tracker := getattr(frame, "tracker", None)) is not None
            )
            if len(trackers) != len(image_frames):
                raise ServiceConfigurationError("ZeroMQ 图片 frame 缺少 MessageTracker")
            return _PreparedZeroMqReply(
                frames=[manifest_bytes, *image_frames],
                reservation=reservation,
                cleanup=cleanup,
            )
        except Exception:
            if reservation is not None:
                self._transport_registry.cancel(
                    reservation=reservation,
                    cleanup=cleanup,
                )
            else:
                cleanup()
            raise

    def _build_output_cleanup(
        self,
        *,
        guard_contexts: list[AbstractContextManager[None]],
        views: list[memoryview],
        receipts: tuple[LeaseOwnershipReceipt, ...],
    ) -> Callable[[], None]:
        """构造严格按 frame、view、guard、lease 顺序执行的一次性清理。"""

        cleanup_lock = RLock()
        cleaned = False

        def cleanup() -> None:
            """tracker 完成后释放当前 reply 的全部本地资源。"""

            nonlocal cleaned
            with cleanup_lock:
                if cleaned:
                    return
                cleaned = True
            first_error: Exception | None = None
            tracker_cleanup_started_at = perf_counter()
            for view in reversed(views):
                try:
                    view.release()
                except Exception as error:
                    first_error = first_error or error
            for guard in reversed(guard_contexts):
                try:
                    guard.__exit__(None, None, None)
                except Exception as error:
                    first_error = first_error or error
            self._record_transport_timing(
                "tracker_cleanup_ms", _elapsed_ms(tracker_cleanup_started_at)
            )
            lease_reclaim_started_at = perf_counter()
            for receipt in receipts:
                try:
                    self.local_buffer_writer.conditional_release(receipt=receipt)
                except Exception as error:
                    first_error = first_error or error
            self._record_transport_timing(
                "lease_reclaim_ms", _elapsed_ms(lease_reclaim_started_at)
            )
            if first_error is not None:
                raise first_error

        return cleanup

    def _serialize_result_manifest(self, manifest: dict[str, object]) -> bytes:
        """序列化 Result manifest，并在诊断模式下写入序列化阶段耗时。"""

        serialize_started_at = perf_counter()
        manifest_bytes = _to_json_bytes(manifest)
        serialize_ms = _elapsed_ms(serialize_started_at)
        self._record_transport_timing("response_json_serialize_ms", serialize_ms)
        metadata = manifest.get("metadata")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("timings"), dict):
            return manifest_bytes
        metadata_payload = dict(metadata)
        timings = dict(metadata_payload["timings"])
        timings["response_json_serialize_ms"] = serialize_ms
        metadata_payload["timings"] = timings
        manifest["metadata"] = metadata_payload
        return _to_json_bytes(manifest)

    def _record_transport_timing(self, name: str, value: float) -> None:
        """保存最近一次 transport 阶段耗时，不记录图片或业务数据。"""

        with self._transport_timing_lock:
            self._transport_timings[name] = value

    def _serve_trigger_source(
        self,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
        state: _ZeroMqAdapterState,
    ) -> None:
        """运行 ZeroMQ REP 监听循环。"""

        zeromq = _load_zeromq_module()
        context = zeromq.Context.instance()
        socket = self._create_rep_socket(zeromq=zeromq, context=context)
        poller = zeromq.Poller()
        try:
            socket.bind(state.bind_endpoint)
            poller.register(socket, zeromq.POLLIN)
            with state.lifecycle_lock:
                state.running = True
                state.stopping = False
            state.startup_event.set()
            while not state.stop_event.is_set():
                events = dict(poller.poll(self.runtime_config.poll_timeout_ms))
                if socket not in events:
                    continue
                receive_started_at = perf_counter()
                frames = socket.recv_multipart()
                receive_ms = _elapsed_ms(receive_started_at)
                try:
                    result = self.handle_multipart_message(
                        trigger_source=trigger_source,
                        frames=list(frames),
                        event_handler=event_handler,
                        receive_ms=receive_ms,
                    )
                    self._send_dispatch_result(
                        socket=socket,
                        zeromq=zeromq,
                        dispatch_result=result,
                        socket_generation=state.socket_generation,
                    )
                except Exception as error:
                    if bool(getattr(socket, "closed", False)):
                        _record_adapter_error(state, error)
                        socket = self._rebuild_rep_socket(
                            zeromq=zeromq,
                            context=context,
                            poller=poller,
                            socket=socket,
                            state=state,
                        )
                        continue
                    try:
                        socket.send_multipart(
                            self.build_error_reply_frames(
                                trigger_source_id=trigger_source.trigger_source_id,
                                error=error,
                            )
                        )
                    except Exception as send_error:
                        _record_adapter_error(state, send_error)
                        socket.close(linger=0)
                        socket = self._rebuild_rep_socket(
                            zeromq=zeromq,
                            context=context,
                            poller=poller,
                            socket=socket,
                            state=state,
                        )
        except Exception as error:
            with state.lifecycle_lock:
                if not state.startup_event.is_set():
                    state.startup_error = str(error) or error.__class__.__name__
            state.startup_event.set()
            _record_adapter_error(state, error)
        finally:
            with state.lifecycle_lock:
                state.running = False
            try:
                poller.unregister(socket)
            except Exception:
                pass
            socket.close(linger=0)
            state.stopped_event.set()

    def _create_rep_socket(self, *, zeromq: Any, context: Any) -> Any:
        """创建并配置一个不保留退出队列的 REP socket。"""

        socket = context.socket(zeromq.REP)
        socket.linger = 0
        socket.setsockopt(zeromq.RCVHWM, self.runtime_config.receive_hwm)
        socket.setsockopt(zeromq.SNDHWM, self.runtime_config.send_hwm)
        socket.setsockopt(
            zeromq.MAXMSGSIZE,
            self.runtime_config.max_message_size_bytes,
        )
        return socket

    def _rebuild_rep_socket(
        self,
        *,
        zeromq: Any,
        context: Any,
        poller: Any,
        socket: Any,
        state: _ZeroMqAdapterState,
    ) -> Any:
        """发送失败后重建 REP 状态机，旧 tracker 继续由 registry 回收。"""

        try:
            poller.unregister(socket)
        except Exception:
            pass
        if not bool(getattr(socket, "closed", False)):
            socket.close(linger=0)
        replacement = self._create_rep_socket(zeromq=zeromq, context=context)
        replacement.bind(state.bind_endpoint)
        poller.register(replacement, zeromq.POLLIN)
        with state.lifecycle_lock:
            state.socket_generation = f"zeromq-socket-{uuid4().hex}"
        return replacement

    def _write_content_to_buffer(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        envelope: ZeroMqFrameEnvelope,
        content: bytes,
    ) -> dict[str, object]:
        """把 ZeroMQ 二进制帧写入 LocalBufferBroker。"""

        pool_name = _read_optional_transport_text(trigger_source, "pool_name")
        ttl_seconds = max(
            self.runtime_config.buffer_ttl_seconds,
            float(trigger_source.reply_timeout_seconds or 300)
            + self.runtime_config.buffer_ttl_safety_margin_seconds,
        )
        media_type = (
            envelope.media_type
            or _read_optional_transport_text(trigger_source, "media_type")
            or "image/octet-stream"
        )
        if media_type.strip().lower() == IMAGE_MEDIA_TYPE_RAW:
            validate_raw_bgr24_bytes(
                image_bytes=content,
                shape=tuple(envelope.shape),
                dtype=envelope.dtype,
                layout=envelope.layout,
                pixel_format=envelope.pixel_format,
            )
        owner_id = f"{trigger_source.trigger_source_id}:{envelope.event_id or 'event'}"
        write_result = self.local_buffer_writer.write_bytes(
            content=content,
            owner_kind="workflow-trigger-source",
            owner_id=owner_id,
            media_type=media_type,
            pool_name=pool_name,
            shape=tuple(envelope.shape),
            dtype=envelope.dtype,
            layout=envelope.layout,
            pixel_format=envelope.pixel_format,
            ttl_seconds=ttl_seconds,
            trace_id=envelope.trace_id,
        )
        buffer_ref = getattr(write_result, "buffer_ref", None)
        if buffer_ref is None or not callable(getattr(buffer_ref, "model_dump", None)):
            raise InvalidRequestError("LocalBufferBroker 写入结果缺少 buffer_ref")
        return dict(buffer_ref.model_dump(mode="json"))

    def _release_buffer_ref_payload(
        self, buffer_ref_payload: dict[str, object] | None
    ) -> None:
        """在没有新 WorkflowRun 接管 cleanup 时释放输入 buffer。

        参数：
        - buffer_ref_payload：已写入 LocalBufferBroker 后返回的 BufferRef payload。
        """

        if buffer_ref_payload is None:
            return
        release = getattr(self.local_buffer_writer, "release", None)
        if not callable(release):
            return
        try:
            buffer_ref = BufferRef.model_validate(buffer_ref_payload)
            pool_name_value = buffer_ref.metadata.get("pool_name")
            release(
                buffer_ref.lease_id,
                pool_name=pool_name_value if isinstance(pool_name_value, str) else None,
            )
        except Exception:
            return

    def _record_result(
        self,
        state: _ZeroMqAdapterState,
        trigger_result: TriggerResultContract,
    ) -> None:
        """把 TriggerResult 计入 adapter health。"""

        if trigger_result.state == "timed_out":
            increment_safe_counter(state.timeout_count)
            with state.lifecycle_lock:
                state.last_error = trigger_result.error_message
            return
        if trigger_result.state == "failed":
            increment_safe_counter(state.error_count)
            with state.lifecycle_lock:
                state.last_error = trigger_result.error_message
            return
        increment_safe_counter(state.submitted_count)
        with state.lifecycle_lock:
            state.last_error = None


def _parse_envelope(frames: list[bytes]) -> ZeroMqFrameEnvelope:
    """解析 ZeroMQ multipart 第一帧 JSON envelope。"""

    if len(frames) < 1:
        raise InvalidRequestError("ZeroMQ 触发消息至少需要 envelope 帧")
    try:
        payload = json.loads(frames[0].decode("utf-8"))
    except Exception as error:
        raise InvalidRequestError("ZeroMQ envelope 必须是 UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise InvalidRequestError("ZeroMQ envelope 必须是 JSON object")
    try:
        return ZeroMqFrameEnvelope.model_validate(payload)
    except ValueError as error:
        raise InvalidRequestError(
            "ZeroMQ envelope 字段不合法", details={"error": str(error)}
        ) from error


def _validate_multipart_frames(
    frames: list[bytes],
    *,
    runtime_config: ZeroMqTriggerRuntimeConfig,
) -> None:
    """限制 envelope/content 两帧协议和单帧大小。"""

    if not 1 <= len(frames) <= 2:
        raise InvalidRequestError(
            "ZeroMQ 触发消息只能包含 envelope 和可选 content 两帧",
            details={"frame_count": len(frames)},
        )
    max_message_size_bytes = runtime_config.max_message_size_bytes
    oversized_frames = [
        index
        for index, frame in enumerate(frames)
        if len(frame) > max_message_size_bytes
    ]
    if oversized_frames:
        raise InvalidRequestError(
            "ZeroMQ 消息帧超过 max_message_size_bytes",
            details={
                "max_message_size_bytes": max_message_size_bytes,
                "frame_indexes": oversized_frames,
            },
        )


def _read_content_frame(frames: list[bytes]) -> bytes | None:
    """读取可选的 ZeroMQ multipart 第二帧二进制内容。"""

    if len(frames) < 2:
        return None
    content = frames[1]
    if not isinstance(content, bytes) or not content:
        raise InvalidRequestError("ZeroMQ content 帧必须是非空 bytes")
    return content


def _merge_trigger_result_timings(
    metadata: dict[str, object],
    timing_payload: dict[str, object],
) -> dict[str, object]:
    """把 ZeroMQ adapter 计时合并进 TriggerResult metadata。"""

    payload = dict(metadata)
    timings = (
        dict(payload.get("timings")) if isinstance(payload.get("timings"), dict) else {}
    )
    for key, value in timing_payload.items():
        if isinstance(value, bool):
            timings[str(key)] = value
            continue
        if isinstance(value, int | float | str) or value is None:
            timings[str(key)] = value
    payload["timings"] = timings
    return payload


def _elapsed_ms(started_at: float) -> float:
    """把 monotonic 起点转换为毫秒耗时。"""

    return round((perf_counter() - started_at) * 1000.0, 3)


def _validate_envelope_target(
    trigger_source: WorkflowTriggerSource, envelope: ZeroMqFrameEnvelope
) -> None:
    """校验 envelope 中的 trigger_source_id 是否匹配。"""

    if envelope.trigger_source_id is None:
        return
    if envelope.trigger_source_id != trigger_source.trigger_source_id:
        raise InvalidRequestError(
            "ZeroMQ envelope 目标 TriggerSource 不匹配",
            details={
                "expected_trigger_source_id": trigger_source.trigger_source_id,
                "actual_trigger_source_id": envelope.trigger_source_id,
            },
        )


def _resolve_input_binding(
    trigger_source: WorkflowTriggerSource, envelope: ZeroMqFrameEnvelope
) -> str:
    """解析二进制内容写入 payload 时使用的字段名。"""

    input_binding = envelope.input_binding or _read_optional_transport_text(
        trigger_source, "default_input_binding"
    )
    if input_binding:
        return _require_stripped_text(input_binding, "input_binding")
    return "request_image_ref"


def _read_required_transport_text(
    trigger_source: WorkflowTriggerSource, field_name: str
) -> str:
    """读取必填 transport_config 文本字段。"""

    value = _read_optional_transport_text(trigger_source, field_name)
    if value is None:
        raise InvalidRequestError(
            f"transport_config.{field_name} 不能为空",
            details={"trigger_source_id": trigger_source.trigger_source_id},
        )
    return value


def _read_optional_transport_text(
    trigger_source: WorkflowTriggerSource, field_name: str
) -> str | None:
    """读取可选 transport_config 文本字段。"""

    value = trigger_source.transport_config.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRequestError(f"transport_config.{field_name} 必须是字符串")
    return _require_stripped_text(value, field_name)


def _read_optional_transport_float(
    trigger_source: WorkflowTriggerSource, field_name: str
) -> float | None:
    """读取可选 transport_config 数值字段。"""

    value = trigger_source.transport_config.get(field_name)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(
            f"transport_config.{field_name} 必须是数字"
        ) from error
    if number <= 0:
        raise InvalidRequestError(f"transport_config.{field_name} 必须大于 0")
    return number


def _record_adapter_error(state: _ZeroMqAdapterState, error: Exception) -> None:
    """记录 adapter 错误计数和最近错误。"""

    increment_safe_counter(state.error_count)
    with state.lifecycle_lock:
        state.last_error = (
            error.message
            if isinstance(error, ServiceError)
            else error.__class__.__name__
        )


def _counter_fields(prefix: str, counter: SafeCounterState) -> dict[str, int]:
    """把 SafeCounterState 转换为统一 health 字段。"""

    snapshot = snapshot_safe_counter(counter)
    return {
        prefix: snapshot["value"],
        f"{prefix}_rollover_count": snapshot["rollover_count"],
    }


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized_value


def _to_json_bytes(payload: dict[str, object]) -> bytes:
    """把 dict 编码为 UTF-8 JSON bytes。"""

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _build_zeromq_result_manifest(
    *,
    dispatch_result: WorkflowTriggerDispatchResult,
    prepared_result: PreparedTriggerResult,
    frame_indexes: dict[str, int],
) -> dict[str, object]:
    """构造 Result v1 manifest；公开 payload 只携带 frame index 和稳定元数据。"""

    payloads = [
        _build_zeromq_physical_payload(item, frame_indexes=frame_indexes)
        for item in prepared_result.physical_payloads
    ]
    response_payload = {
        "results": dict(prepared_result.selected_results),
        "attachments": [
            item.model_dump(mode="json") for item in prepared_result.attachments
        ],
        "payloads": payloads,
    }
    result = dispatch_result.trigger_result.model_copy(
        update={"response_payload": response_payload}
    )
    return result.model_dump(mode="json")


def _build_zeromq_physical_payload(
    item: PreparedPhysicalPayload,
    *,
    frame_indexes: dict[str, int],
) -> dict[str, object]:
    """把私有 LocalBuffer locator 转换为 ZeroMQ 物理 frame locator。"""

    frame_index = frame_indexes.get(item.payload_id)
    if frame_index is None:
        raise ServiceConfigurationError(
            "ZeroMQ Result manifest 缺少物理 frame",
            details={"payload_id": item.payload_id},
        )
    return {
        "payload_id": item.payload_id,
        "delivery_kind": "zeromq-frame",
        "frame_index": frame_index,
        "media_type": item.media_type,
        "content_length": item.content_length,
        "checksum_algorithm": item.checksum_algorithm,
        "checksum": item.checksum,
        "width": item.width,
        "height": item.height,
        "shape": list(item.shape),
        "dtype": item.dtype,
        "layout": item.layout,
        "pixel_format": item.pixel_format,
    }


def _load_zeromq_module() -> Any:
    """按需导入 pyzmq。"""

    try:
        import zmq
    except ImportError as error:
        raise InvalidRequestError("当前 Python 环境未安装 pyzmq") from error
    return zmq
