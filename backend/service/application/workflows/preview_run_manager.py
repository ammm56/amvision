"""Preview Run 记录与 JSONL 事件存储。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import BinaryIO

from backend.contracts.workflows.resource_semantics import build_workflow_preview_run_events_object_key
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.application.events import ServiceEvent
from backend.service.application.project_summary import (
    PROJECT_SUMMARY_TOPIC_WORKFLOW_PREVIEW_RUNS,
    publish_project_summary_event,
    should_publish_project_summary_for_preview_event,
)
from backend.service.application.workflows.runtime_payload_sanitizer import (
    sanitize_runtime_mapping,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowPreviewRun,
    WorkflowPreviewRunEvent,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


LOGGER = logging.getLogger(__name__)
_JSONL_TAIL_READ_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class WorkflowPreviewRunExecutionRequest:
    """描述一条在当前服务进程直接执行的 Preview 请求。"""

    preview_run_id: str
    project_id: str
    application_id: str
    application_snapshot_object_key: str
    template_snapshot_object_key: str
    input_bindings: dict[str, object] = field(default_factory=dict)
    execution_metadata: dict[str, object] = field(default_factory=dict)
    timeout_seconds: int = 30
    retain_node_records_enabled: bool = True
    return_sync_response_payload_enabled: bool = True
    target_node_id: str | None = None


class WorkflowPreviewRunManager:
    """提供 Preview Run 查询、状态更新和单事件 JSONL 追加。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 Preview Run 存储管理器。"""

        self.session_factory = session_factory
        self.service_event_bus = getattr(session_factory, "service_event_bus", None)
        self.dataset_storage = dataset_storage
        self._lock = Lock()
        self._event_locks: dict[str, Lock] = {}
        self._event_sequences: dict[str, int] = {}
        self._event_streams: dict[str, BinaryIO] = {}

    def initialize_event_stream(self, preview_run_id: str) -> float:
        """为新 Preview Run 创建唯一的空 events.jsonl。"""

        started_at = perf_counter()
        event_lock = self._resolve_event_lock(preview_run_id)
        with event_lock:
            events_path = self._events_path(preview_run_id)
            events_path.parent.mkdir(parents=True, exist_ok=True)
            event_stream = events_path.open("wb")
            with self._lock:
                previous_stream = self._event_streams.pop(preview_run_id, None)
                self._event_streams[preview_run_id] = event_stream
                self._event_sequences[preview_run_id] = 0
            if previous_stream is not None:
                previous_stream.close()
        return _elapsed_milliseconds(started_at)

    def append_event(
        self,
        preview_run_id: str,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object],
    ) -> tuple[WorkflowPreviewRunEvent, float]:
        """构造一条事件并直接追加一行 JSONL。"""

        persist_started_at = perf_counter()
        event_lock = self._resolve_event_lock(preview_run_id)
        with event_lock:
            sequence = self._next_event_sequence(preview_run_id)
            normalized_event_type = event_type.strip() or "workflow.event"
            normalized_message = message.strip() or normalized_event_type
            event = WorkflowPreviewRunEvent(
                preview_run_id=preview_run_id,
                sequence=sequence,
                event_type=normalized_event_type,
                created_at=_now_isoformat(),
                message=normalized_message,
                payload=sanitize_runtime_mapping(payload),
            )
            events_path = self._events_path(preview_run_id)
            events_path.parent.mkdir(parents=True, exist_ok=True)
            encoded_line = (
                json.dumps(
                    _serialize_preview_run_event(event),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            event_stream = self._resolve_event_stream(
                preview_run_id,
                events_path=events_path,
            )
            event_stream.write(encoded_line)
        persist_ms = _elapsed_milliseconds(persist_started_at)
        self._publish_preview_run_event(event)
        try:
            self._publish_project_summary_event(preview_run_id, event)
        except Exception:
            LOGGER.exception(
                "workflow preview run project summary event publish failed",
                extra={
                    "preview_run_id": preview_run_id,
                    "event_type": event.event_type,
                },
            )
        if event.event_type in {
            "preview.succeeded",
            "preview.failed",
            "preview.timed_out",
        }:
            self._release_event_state(preview_run_id)
        return event, persist_ms

    def list_events(
        self,
        preview_run_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[WorkflowPreviewRunEvent, ...]:
        """按顺序读取 events.jsonl 中的有效事件。"""

        if after_sequence is not None and after_sequence < 0:
            raise InvalidRequestError("after_sequence 不能小于 0")
        if limit is not None and limit <= 0:
            raise InvalidRequestError("limit 必须大于 0")
        event_lock = self._resolve_event_lock(preview_run_id)
        with event_lock:
            self._flush_event_stream(preview_run_id)
            events = self._read_events(preview_run_id)
        if after_sequence is not None:
            events = tuple(item for item in events if item.sequence > after_sequence)
        return events if limit is None else events[:limit]

    def get_preview_run(self, preview_run_id: str) -> WorkflowPreviewRun:
        """按 id 读取 Preview Run。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
        if preview_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowPreviewRun 不存在",
                details={"preview_run_id": preview_run_id},
            )
        return preview_run

    def _events_path(self, preview_run_id: str) -> Path:
        """返回 Preview Run 的 events.jsonl 本地路径。"""

        return self.dataset_storage.resolve(
            build_workflow_preview_run_events_object_key(preview_run_id)
        )

    def _read_events(self, preview_run_id: str) -> tuple[WorkflowPreviewRunEvent, ...]:
        """只从当前 events.jsonl 读取事件。"""

        events_path = self._events_path(preview_run_id)
        if not events_path.is_file():
            return ()
        events: list[WorkflowPreviewRunEvent] = []
        with events_path.open("r", encoding="utf-8", errors="replace") as event_stream:
            for line in event_stream:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = _deserialize_preview_run_event(preview_run_id, item)
                if event is not None:
                    events.append(event)
        return tuple(events)

    def _next_event_sequence(self, preview_run_id: str) -> int:
        """在事件文件锁内生成下一序号。"""

        with self._lock:
            sequence = self._event_sequences.get(preview_run_id)
        if sequence is None:
            _ensure_jsonl_append_boundary(self._events_path(preview_run_id))
            sequence = _read_last_valid_event_sequence(
                self._events_path(preview_run_id),
                preview_run_id=preview_run_id,
            )
        sequence += 1
        with self._lock:
            self._event_sequences[preview_run_id] = sequence
        return sequence

    def _resolve_event_lock(self, preview_run_id: str) -> Lock:
        """返回单个 Preview Run 的事件写锁。"""

        with self._lock:
            event_lock = self._event_locks.get(preview_run_id)
            if event_lock is None:
                event_lock = Lock()
                self._event_locks[preview_run_id] = event_lock
            return event_lock

    def _resolve_event_stream(
        self,
        preview_run_id: str,
        *,
        events_path: Path,
    ) -> BinaryIO:
        """返回当前 Preview 的 JSONL 追加句柄。"""

        with self._lock:
            event_stream = self._event_streams.get(preview_run_id)
            if event_stream is not None:
                return event_stream
            event_stream = events_path.open("ab")
            self._event_streams[preview_run_id] = event_stream
            return event_stream

    def flush_event_stream(self, preview_run_id: str) -> float:
        """把当前 Preview 已逐行写入的事件刷新到文件。"""

        started_at = perf_counter()
        event_lock = self._resolve_event_lock(preview_run_id)
        with event_lock:
            self._flush_event_stream(preview_run_id)
        return _elapsed_milliseconds(started_at)

    def _flush_event_stream(self, preview_run_id: str) -> None:
        """在事件锁内刷新当前 Preview 的 JSONL 句柄。"""

        with self._lock:
            event_stream = self._event_streams.get(preview_run_id)
        if event_stream is not None:
            event_stream.flush()

    def _release_event_state(self, preview_run_id: str) -> None:
        """终态后释放进程内序号和锁索引。"""

        with self._lock:
            self._event_sequences.pop(preview_run_id, None)
            self._event_locks.pop(preview_run_id, None)
            event_stream = self._event_streams.pop(preview_run_id, None)
        if event_stream is not None:
            event_stream.close()

    def close(self) -> None:
        """关闭仍在执行中的 Preview JSONL 追加句柄。"""

        with self._lock:
            event_streams = tuple(self._event_streams.values())
            self._event_streams.clear()
            self._event_sequences.clear()
            self._event_locks.clear()
        for event_stream in event_streams:
            event_stream.close()

    def _publish_preview_run_event(self, event: WorkflowPreviewRunEvent) -> None:
        """把新事件同步发布到服务事件总线。"""

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
        """为 Preview 生命周期事件发布项目摘要更新。"""

        if not should_publish_project_summary_for_preview_event(event.event_type):
            return
        with self._open_unit_of_work() as unit_of_work:
            preview_run = unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
        if preview_run is None:
            return
        publish_project_summary_event(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
            service_event_bus=self.service_event_bus,
            project_id=preview_run.project_id,
            topic=PROJECT_SUMMARY_TOPIC_WORKFLOW_PREVIEW_RUNS,
            source_stream="workflows.preview-runs.events",
            source_resource_kind="workflow_preview_run",
            source_resource_id=preview_run_id,
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并管理一个 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()


def _serialize_preview_run_event(event: WorkflowPreviewRunEvent) -> dict[str, object]:
    """把事件转换为 JSON 字典。"""

    return {
        "preview_run_id": event.preview_run_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "created_at": event.created_at,
        "message": event.message,
        "payload": dict(event.payload),
    }


def _deserialize_preview_run_event(
    preview_run_id: str,
    value: object,
) -> WorkflowPreviewRunEvent | None:
    """把一行 JSON 字典转换为事件，无效行返回 None。"""

    if not isinstance(value, dict):
        return None
    sequence = value.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        return None
    event_type = value.get("event_type")
    created_at = value.get("created_at")
    message = value.get("message")
    if not all(isinstance(item, str) and item for item in (event_type, created_at, message)):
        return None
    payload = value.get("payload")
    return WorkflowPreviewRunEvent(
        preview_run_id=preview_run_id,
        sequence=sequence,
        event_type=event_type,
        created_at=created_at,
        message=message,
        payload=payload if isinstance(payload, dict) else {},
    )


def _read_last_valid_event_sequence(
    events_path: Path,
    *,
    preview_run_id: str,
) -> int:
    """服务重启后从 JSONL 文件尾恢复最后一个有效序号。"""

    if not events_path.is_file():
        return 0
    with events_path.open("rb") as event_stream:
        event_stream.seek(0, 2)
        position = event_stream.tell()
        suffix = b""
        while position > 0:
            read_size = min(_JSONL_TAIL_READ_CHUNK_SIZE, position)
            position -= read_size
            event_stream.seek(position)
            chunk = event_stream.read(read_size) + suffix
            lines = chunk.split(b"\n")
            suffix = lines[0]
            for raw_line in reversed(lines[1:]):
                sequence = _read_preview_event_sequence_from_line(
                    raw_line,
                    preview_run_id=preview_run_id,
                )
                if sequence is not None:
                    return sequence
        sequence = _read_preview_event_sequence_from_line(
            suffix,
            preview_run_id=preview_run_id,
        )
        return sequence or 0


def _read_preview_event_sequence_from_line(
    raw_line: bytes,
    *,
    preview_run_id: str,
) -> int | None:
    """解析单行并返回有效 Preview 事件序号。"""

    if not raw_line.strip():
        return None
    try:
        value = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    event = _deserialize_preview_run_event(preview_run_id, value)
    return event.sequence if event is not None else None


def _ensure_jsonl_append_boundary(events_path: Path) -> None:
    """服务重启后为异常退出留下的半行补一个换行边界。"""

    if not events_path.is_file() or events_path.stat().st_size == 0:
        return
    with events_path.open("rb+") as event_stream:
        event_stream.seek(-1, 2)
        if event_stream.read(1) != b"\n":
            event_stream.seek(0, 2)
            event_stream.write(b"\n")


def _now_isoformat() -> str:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _elapsed_milliseconds(started_at: float) -> float:
    """返回从 started_at 到当前的毫秒数。"""

    return round(max(0.0, (perf_counter() - started_at) * 1000.0), 3)
