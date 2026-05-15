"""preview run 长生命周期管理器。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from queue import Empty
from threading import Event, Lock, Thread
from time import monotonic

from backend.contracts.workflows.resource_semantics import (
    WORKFLOW_PREVIEW_RUN_TERMINAL_STATES,
    build_workflow_preview_run_events_object_key,
)
from backend.service.application.events import ServiceEvent
from backend.service.application.deployments import PublishedInferenceGateway
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ResourceNotFoundError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.project_summary import (
    PROJECT_SUMMARY_TOPIC_WORKFLOW_PREVIEW_RUNS,
    publish_project_summary_event,
    should_publish_project_summary_for_preview_event,
)
from backend.service.application.local_buffers import LocalBufferBrokerEventChannel
from backend.service.application.workflows.runtime_payload_sanitizer import (
    sanitize_runtime_mapping,
    serialize_node_execution_record,
)
from backend.service.application.workflows.snapshot_execution import (
    WorkflowSnapshotExecutionRequest,
    WorkflowSnapshotExecutionResult,
    WorkflowSnapshotProcessExecutor,
    WorkflowSnapshotProcessHandle,
    deserialize_snapshot_execution_result,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowPreviewRun,
    WorkflowPreviewRunEvent,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings


@dataclass(frozen=True)
class WorkflowPreviewRunExecutionRequest:
    """描述一条交给 preview manager 托管执行的请求。"""

    preview_run_id: str
    project_id: str
    application_id: str
    application_snapshot_object_key: str
    template_snapshot_object_key: str
    input_bindings: dict[str, object] = field(default_factory=dict)
    execution_metadata: dict[str, object] = field(default_factory=dict)
    timeout_seconds: int = 30
    retain_node_records_enabled: bool = True


@dataclass
class _ActiveWorkflowPreviewRun:
    """描述一条正在父进程中被观察的 preview run。"""

    request: WorkflowPreviewRunExecutionRequest
    executor: WorkflowSnapshotProcessExecutor
    handle: WorkflowSnapshotProcessHandle
    cancel_event: Event = field(default_factory=Event, repr=False)
    completion_event: Event = field(default_factory=Event, repr=False)
    event_lock: Lock = field(default_factory=Lock, repr=False)
    thread: Thread | None = field(default=None, repr=False)


class WorkflowPreviewRunManager:
    """管理 preview run 子进程、过程事件和取消语义。"""

    def __init__(
        self,
        *,
        settings: BackendServiceSettings,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        local_buffer_broker_event_channel_provider: Callable[[], LocalBufferBrokerEventChannel | None] | None = None,
        published_inference_gateway: PublishedInferenceGateway | None = None,
    ) -> None:
        """初始化 preview run 管理器。"""

        self.settings = settings
        self.session_factory = session_factory
        self.service_event_bus = getattr(session_factory, "service_event_bus", None)
        self.dataset_storage = dataset_storage
        self.local_buffer_broker_event_channel_provider = local_buffer_broker_event_channel_provider
        self.published_inference_gateway = published_inference_gateway
        self._active_runs: dict[str, _ActiveWorkflowPreviewRun] = {}
        self._lock = Lock()
        self._stopping = Event()

    def start(self) -> None:
        """启动管理器本身。"""

        self._stopping.clear()

    def stop(self) -> None:
        """停止全部活动 preview run，并等待后台观察线程收口。"""

        self._stopping.set()
        with self._lock:
            active_runs = tuple(self._active_runs.values())
        for active_run in active_runs:
            active_run.cancel_event.set()
            active_run.executor.terminate(active_run.handle)
        for active_run in active_runs:
            active_run.completion_event.wait(timeout=1.0)

    def submit_run(self, request: WorkflowPreviewRunExecutionRequest) -> None:
        """提交一条 preview run，并异步观察其生命周期。"""

        if self._stopping.is_set():
            raise ServiceConfigurationError("workflow preview run manager 已停止")
        with self._lock:
            if request.preview_run_id in self._active_runs:
                raise InvalidRequestError(
                    "preview run 已在执行中",
                    details={"preview_run_id": request.preview_run_id},
                )

        executor = WorkflowSnapshotProcessExecutor(
            settings=self.settings,
            request_timeout_seconds=request.timeout_seconds,
            local_buffer_broker_event_channel=self._resolve_local_buffer_broker_event_channel(),
            published_inference_gateway=self.published_inference_gateway,
        )
        handle = executor.start(
            WorkflowSnapshotExecutionRequest(
                project_id=request.project_id,
                application_id=request.application_id,
                application_snapshot_object_key=request.application_snapshot_object_key,
                template_snapshot_object_key=request.template_snapshot_object_key,
                input_bindings=dict(request.input_bindings),
                execution_metadata=dict(request.execution_metadata),
            )
        )
        active_run = _ActiveWorkflowPreviewRun(
            request=request,
            executor=executor,
            handle=handle,
        )
        try:
            self._write_events(active_run.request.preview_run_id, (), event_lock=active_run.event_lock)
            self._append_event(
                active_run.request.preview_run_id,
                event_type="preview.started",
                message="preview run started",
                payload={"state": "running"},
                event_lock=active_run.event_lock,
            )
            thread = Thread(
                target=self._observe_active_run,
                args=(active_run,),
                name=f"workflow-preview-{request.preview_run_id}",
                daemon=True,
            )
            active_run.thread = thread
            with self._lock:
                self._active_runs[request.preview_run_id] = active_run
            thread.start()
        except Exception:
            with self._lock:
                self._active_runs.pop(request.preview_run_id, None)
            executor.close_handle(handle)
            raise

    def wait_for_completion(
        self,
        preview_run_id: str,
        *,
        timeout_seconds: float,
    ) -> WorkflowPreviewRun:
        """等待一条 preview run 进入终态。"""

        active_run = self._get_active_run(preview_run_id)
        if active_run is None:
            return self.get_preview_run(preview_run_id)
        if not active_run.completion_event.wait(timeout=max(0.1, timeout_seconds)):
            raise OperationTimeoutError(
                "等待 workflow preview run 完成超时",
                details={
                    "preview_run_id": preview_run_id,
                    "timeout_seconds": timeout_seconds,
                },
            )
        return self.get_preview_run(preview_run_id)

    def list_events(
        self,
        preview_run_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[WorkflowPreviewRunEvent, ...]:
        """读取一条 preview run 的过程事件。

        参数：
        - preview_run_id：目标 preview run id。
        - after_sequence：可选事件下界；只返回 sequence 更大的事件。
        - limit：可选返回条数上限；为空时返回全部命中的事件。

        返回：
        - tuple[WorkflowPreviewRunEvent, ...]：按 sequence 升序排列的事件列表。
        """

        if after_sequence is not None and after_sequence < 0:
            raise InvalidRequestError("after_sequence 不能小于 0")
        if limit is not None and limit <= 0:
            raise InvalidRequestError("limit 必须大于 0")
        event_lock = self._resolve_event_lock(preview_run_id)
        with event_lock:
            events = self._read_events(preview_run_id)
        if after_sequence is not None:
            events = tuple(item for item in events if item.sequence > after_sequence)
        if limit is None:
            return events
        return events[:limit]

    def cancel_run(self, preview_run_id: str, *, cancelled_by: str | None) -> WorkflowPreviewRun:
        """取消一条正在执行的 preview run。"""

        preview_run = self.get_preview_run(preview_run_id)
        if preview_run.state in WORKFLOW_PREVIEW_RUN_TERMINAL_STATES:
            return preview_run

        metadata = dict(preview_run.metadata)
        metadata["cancel_requested_at"] = _now_isoformat()
        normalized_cancelled_by = _normalize_optional_str(cancelled_by)
        if normalized_cancelled_by is not None:
            metadata["cancelled_by"] = normalized_cancelled_by
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_preview_run(replace(preview_run, metadata=metadata))
            unit_of_work.commit()

        active_run = self._get_active_run(preview_run_id)
        if active_run is None:
            updated_preview_run = self._mark_run_cancelled(preview_run_id)
            self._append_event(
                preview_run_id,
                event_type="preview.cancelled",
                message="preview run cancelled",
                payload={"state": "cancelled", "error_message": updated_preview_run.error_message},
            )
            return updated_preview_run

        active_run.cancel_event.set()
        active_run.completion_event.wait(timeout=5.0)
        return self.get_preview_run(preview_run_id)

    def get_preview_run(self, preview_run_id: str) -> WorkflowPreviewRun:
        """按 id 读取一个 preview run。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
        if preview_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowPreviewRun 不存在",
                details={"preview_run_id": preview_run_id},
            )
        return preview_run

    def _observe_active_run(self, active_run: _ActiveWorkflowPreviewRun) -> None:
        """在后台线程里观察单条 preview run 的执行过程。"""

        deadline = monotonic() + float(active_run.request.timeout_seconds)
        preview_run_id = active_run.request.preview_run_id
        try:
            while True:
                self._drain_child_events(active_run)
                if active_run.cancel_event.is_set():
                    active_run.executor.terminate(active_run.handle)
                    updated_preview_run = self._mark_run_cancelled(preview_run_id)
                    self._append_event(
                        preview_run_id,
                        event_type="preview.cancelled",
                        message="preview run cancelled",
                        payload={"state": "cancelled", "error_message": updated_preview_run.error_message},
                        event_lock=active_run.event_lock,
                    )
                    return

                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    active_run.executor.terminate(active_run.handle)
                    error = OperationTimeoutError(
                        "等待 workflow snapshot 子进程响应超时",
                        details={
                            "preview_run_id": preview_run_id,
                            "timeout_seconds": active_run.request.timeout_seconds,
                        },
                    )
                    updated_preview_run = self._mark_run_timed_out(preview_run_id, error)
                    self._append_event(
                        preview_run_id,
                        event_type="preview.timed_out",
                        message="preview run timed out",
                        payload={"state": "timed_out", "error_message": updated_preview_run.error_message},
                        event_lock=active_run.event_lock,
                    )
                    return

                try:
                    message = active_run.handle.response_queue.get(
                        timeout=max(0.1, min(0.2, remaining_seconds))
                    )
                except Empty:
                    if not active_run.handle.process.is_alive():
                        error = ServiceConfigurationError(
                            "workflow snapshot 子进程已退出且未返回结果",
                            details={"preview_run_id": preview_run_id},
                        )
                        updated_preview_run = self._mark_run_failed(preview_run_id, error)
                        self._append_event(
                            preview_run_id,
                            event_type="preview.failed",
                            message="preview run failed",
                            payload={"state": "failed", "error_message": updated_preview_run.error_message},
                            event_lock=active_run.event_lock,
                        )
                        return
                    continue

                self._drain_child_events(active_run)
                try:
                    execution_result = deserialize_snapshot_execution_result(message)
                except OperationTimeoutError as exc:
                    updated_preview_run = self._mark_run_timed_out(preview_run_id, exc)
                    self._append_event(
                        preview_run_id,
                        event_type="preview.timed_out",
                        message="preview run timed out",
                        payload={"state": "timed_out", "error_message": updated_preview_run.error_message},
                        event_lock=active_run.event_lock,
                    )
                    return
                except ServiceError as exc:
                    updated_preview_run = self._mark_run_failed(preview_run_id, exc)
                    self._append_event(
                        preview_run_id,
                        event_type="preview.failed",
                        message="preview run failed",
                        payload={"state": "failed", "error_message": updated_preview_run.error_message},
                        event_lock=active_run.event_lock,
                    )
                    return

                updated_preview_run = self._mark_run_succeeded(
                    preview_run_id,
                    execution_result,
                    retain_node_records_enabled=active_run.request.retain_node_records_enabled,
                )
                self._append_event(
                    preview_run_id,
                    event_type="preview.succeeded",
                    message="preview run succeeded",
                    payload={"state": "succeeded"},
                    event_lock=active_run.event_lock,
                )
                return
        finally:
            try:
                self._drain_child_events(active_run)
            except ServiceError:
                pass
            active_run.executor.close_handle(active_run.handle)
            with self._lock:
                self._active_runs.pop(preview_run_id, None)
            active_run.completion_event.set()

    def _drain_child_events(self, active_run: _ActiveWorkflowPreviewRun) -> None:
        """把子进程已经产生的过程事件持久化到 events.json。"""

        while True:
            child_event = active_run.executor.read_event(active_run.handle)
            if child_event is None:
                return
            self._append_event(
                active_run.request.preview_run_id,
                event_type=str(child_event.get("event_type") or "workflow.event"),
                message=str(child_event.get("message") or child_event.get("event_type") or "workflow event"),
                payload=child_event.get("payload") if isinstance(child_event.get("payload"), dict) else {},
                event_lock=active_run.event_lock,
            )

    def _mark_run_succeeded(
        self,
        preview_run_id: str,
        execution_result: WorkflowSnapshotExecutionResult,
        *,
        retain_node_records_enabled: bool,
    ) -> WorkflowPreviewRun:
        """把 preview run 更新为 succeeded。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = self._require_preview_run(unit_of_work, preview_run_id)
            updated_preview_run = replace(
                preview_run,
                state="succeeded",
                finished_at=_now_isoformat(),
                outputs=sanitize_runtime_mapping(execution_result.outputs),
                template_outputs=sanitize_runtime_mapping(execution_result.template_outputs),
                node_records=(
                    tuple(serialize_node_execution_record(item) for item in execution_result.node_records)
                    if retain_node_records_enabled
                    else ()
                ),
                error_message=None,
            )
            unit_of_work.workflow_runtime.save_preview_run(updated_preview_run)
            unit_of_work.commit()
        return updated_preview_run

    def _mark_run_failed(
        self,
        preview_run_id: str,
        error: ServiceError,
    ) -> WorkflowPreviewRun:
        """把 preview run 更新为 failed。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = self._require_preview_run(unit_of_work, preview_run_id)
            updated_preview_run = replace(
                preview_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=error.message,
            )
            unit_of_work.workflow_runtime.save_preview_run(updated_preview_run)
            unit_of_work.commit()
        return updated_preview_run

    def _mark_run_timed_out(
        self,
        preview_run_id: str,
        error: OperationTimeoutError,
    ) -> WorkflowPreviewRun:
        """把 preview run 更新为 timed_out。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = self._require_preview_run(unit_of_work, preview_run_id)
            updated_preview_run = replace(
                preview_run,
                state="timed_out",
                finished_at=_now_isoformat(),
                error_message=error.message,
            )
            unit_of_work.workflow_runtime.save_preview_run(updated_preview_run)
            unit_of_work.commit()
        return updated_preview_run

    def _mark_run_cancelled(self, preview_run_id: str) -> WorkflowPreviewRun:
        """把 preview run 更新为 cancelled。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = self._require_preview_run(unit_of_work, preview_run_id)
            updated_preview_run = replace(
                preview_run,
                state="cancelled",
                finished_at=_now_isoformat(),
                error_message="workflow preview run 已取消",
            )
            unit_of_work.workflow_runtime.save_preview_run(updated_preview_run)
            unit_of_work.commit()
        return updated_preview_run

    def _append_event(
        self,
        preview_run_id: str,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object],
        event_lock: Lock | None = None,
    ) -> WorkflowPreviewRunEvent:
        """向 preview run 的 events.json 追加一条事件。"""

        active_event_lock = event_lock or self._resolve_event_lock(preview_run_id)
        with active_event_lock:
            existing_events = list(self._read_events(preview_run_id))
            new_event = WorkflowPreviewRunEvent(
                preview_run_id=preview_run_id,
                sequence=len(existing_events) + 1,
                event_type=event_type.strip() or "workflow.event",
                created_at=_now_isoformat(),
                message=message.strip() or event_type.strip() or "workflow event",
                payload=sanitize_runtime_mapping(payload),
            )
            existing_events.append(new_event)
            self._write_events(preview_run_id, tuple(existing_events), event_lock=active_event_lock)
            self._publish_preview_run_event(new_event)
        self._publish_project_summary_event(preview_run_id, new_event)
        return new_event

    def _publish_preview_run_event(self, event: WorkflowPreviewRunEvent) -> None:
        """把 preview run 事件同步发布到统一服务内事件总线。

        参数：
        - event：刚写入 events.json 的 preview run 事件。
        """

        if self.service_event_bus is None:
            return
        self.service_event_bus.publish(
            ServiceEvent(
                stream="workflows.preview-runs.events",
                resource_kind="workflow_preview_run",
                resource_id=event.preview_run_id,
                event_type=event.event_type,
                occurred_at=event.created_at,
                cursor=str(event.sequence),
                payload={
                    "preview_run_id": event.preview_run_id,
                    "sequence": event.sequence,
                    "message": event.message,
                    **dict(event.payload),
                },
            )
        )

    def _publish_project_summary_event(
        self,
        preview_run_id: str,
        event: WorkflowPreviewRunEvent,
    ) -> None:
        """按需为 preview run 生命周期事件发布项目级聚合更新。"""

        if not should_publish_project_summary_for_preview_event(event.event_type):
            return
        project_id = self._resolve_preview_run_project_id(preview_run_id)
        if project_id is None:
            return
        publish_project_summary_event(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            service_event_bus=self.service_event_bus,
            project_id=project_id,
            topic=PROJECT_SUMMARY_TOPIC_WORKFLOW_PREVIEW_RUNS,
            source_stream="workflows.preview-runs.events",
            source_resource_kind="workflow_preview_run",
            source_resource_id=preview_run_id,
        )

    def _resolve_preview_run_project_id(self, preview_run_id: str) -> str | None:
        """解析一条 preview run 对应的 Project id。"""

        active_run = self._get_active_run(preview_run_id)
        if active_run is not None:
            return active_run.request.project_id
        with self._open_unit_of_work() as unit_of_work:
            preview_run = unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
        if preview_run is None:
            return None
        return preview_run.project_id

    def _read_events(self, preview_run_id: str) -> tuple[WorkflowPreviewRunEvent, ...]:
        """读取一条 preview run 的全部事件。"""

        object_key = build_workflow_preview_run_events_object_key(preview_run_id)
        if not self.dataset_storage.resolve(object_key).exists():
            return ()
        payload = self.dataset_storage.read_json(object_key)
        if not isinstance(payload, list):
            raise ServiceConfigurationError(
                "preview run 事件文件格式无效",
                details={"preview_run_id": preview_run_id},
            )
        events: list[WorkflowPreviewRunEvent] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            sequence = item.get("sequence")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
                continue
            created_at = item.get("created_at") if isinstance(item.get("created_at"), str) else ""
            event_type = item.get("event_type") if isinstance(item.get("event_type"), str) else ""
            message = item.get("message") if isinstance(item.get("message"), str) else ""
            payload_value = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            if not created_at or not event_type or not message:
                continue
            events.append(
                WorkflowPreviewRunEvent(
                    preview_run_id=preview_run_id,
                    sequence=sequence,
                    event_type=event_type,
                    created_at=created_at,
                    message=message,
                    payload=payload_value,
                )
            )
        return tuple(events)

    def _write_events(
        self,
        preview_run_id: str,
        events: tuple[WorkflowPreviewRunEvent, ...],
        *,
        event_lock: Lock | None = None,
    ) -> None:
        """把 preview run 事件列表写回 events.json。"""

        _ = event_lock
        object_key = build_workflow_preview_run_events_object_key(preview_run_id)
        payload = [
            {
                "preview_run_id": item.preview_run_id,
                "sequence": item.sequence,
                "event_type": item.event_type,
                "created_at": item.created_at,
                "message": item.message,
                "payload": sanitize_runtime_mapping(item.payload),
            }
            for item in events
        ]
        self.dataset_storage.write_json(object_key, payload)

    def _resolve_event_lock(self, preview_run_id: str) -> Lock:
        """返回指定 preview run 事件文件对应的写锁。"""

        active_run = self._get_active_run(preview_run_id)
        if active_run is not None:
            return active_run.event_lock
        return self._lock

    def _get_active_run(self, preview_run_id: str) -> _ActiveWorkflowPreviewRun | None:
        """按 id 返回当前活动 preview run 句柄。"""

        with self._lock:
            return self._active_runs.get(preview_run_id)

    def _resolve_local_buffer_broker_event_channel(self) -> LocalBufferBrokerEventChannel | None:
        """读取当前 preview run 可复用的 LocalBufferBroker 事件通道。"""

        if self.local_buffer_broker_event_channel_provider is None:
            return None
        return self.local_buffer_broker_event_channel_provider()

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并管理一个 preview manager 使用的 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()

    @staticmethod
    def _require_preview_run(unit_of_work: SqlAlchemyUnitOfWork, preview_run_id: str) -> WorkflowPreviewRun:
        """从持久化层中读取一个必然存在的 preview run。"""

        preview_run = unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
        if preview_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowPreviewRun 不存在",
                details={"preview_run_id": preview_run_id},
            )
        return preview_run


def _normalize_optional_str(value: str | None) -> str | None:
    """把可选字符串规范化为去空白后的值。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()