"""目录变化通知 TriggerSource adapter。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread
from uuid import uuid4

from watchfiles import Change, watch

from backend.contracts.workflows import DirectoryChangeEventContract
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.support.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)
from backend.service.application.workflows.trigger_sources.protocol_adapter import (
    WorkflowTriggerEventHandler,
)
from backend.service.application.workflows.trigger_sources.trigger_event_normalizer import (
    RawTriggerEvent,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.integrations.directory._directory_trigger_support import (
    DirectoryWatchTriggerConfig,
    matches_directory_candidate_path,
    parse_directory_watch_trigger_config,
)
from backend.service.infrastructure.integrations.directory.directory_change_window import (
    DirectoryChangeWindowAccumulator,
    DirectoryChangeWindowSnapshot,
    MatchedDirectoryChange,
)


DIRECTORY_EVENT_MAX_BYTES = 64 * 1024
_WATCH_DEBOUNCE_MS = 50
_WATCH_STEP_MS = 50
_WATCH_TIMEOUT_MS = 100
_LATE_WINDOW_THRESHOLD_SECONDS = 0.5
_CHANGE_NAME_BY_KIND = {
    Change.added: "created",
    Change.modified: "modified",
    Change.deleted: "deleted",
}


@dataclass
class _DirectoryWatchAdapterState:
    """描述一条 directory-watch TriggerSource 的有界运行状态。"""

    trigger_source_id: str
    config: DirectoryWatchTriggerConfig
    stop_event: Event
    accumulator: DirectoryChangeWindowAccumulator
    startup_event: Event = field(default_factory=Event)
    state_lock: RLock = field(default_factory=RLock)
    thread: Thread | None = None
    running: bool = False
    stop_requested: bool = False
    submit_call_in_progress: bool = False
    startup_error: str | None = None
    last_error: str | None = None
    last_change_at: str | None = None
    last_submitted_at: str | None = None
    last_workflow_run_id: str | None = None
    last_submission_state: str | None = None
    last_submit_duration_ms: float | None = None
    max_submit_duration_ms: float = 0.0
    watch_batch_count: SafeCounterState = field(default_factory=SafeCounterState)
    submitted_count: SafeCounterState = field(default_factory=SafeCounterState)
    success_count: SafeCounterState = field(default_factory=SafeCounterState)
    timeout_count: SafeCounterState = field(default_factory=SafeCounterState)
    coalesced_change_count: SafeCounterState = field(default_factory=SafeCounterState)
    truncated_window_count: SafeCounterState = field(default_factory=SafeCounterState)
    late_window_count: SafeCounterState = field(default_factory=SafeCounterState)
    submit_error_count: SafeCounterState = field(default_factory=SafeCounterState)
    watch_error_count: SafeCounterState = field(default_factory=SafeCounterState)


class DirectoryWatchTriggerAdapter:
    """合并目录变化并按固定窗口提交普通异步 Trigger 调用。"""

    adapter_kind = "directory-watch"

    def __init__(
        self,
        *,
        dataset_storage_root_dir: str,
        startup_timeout_seconds: float = 1.0,
        stop_timeout_seconds: float = 5.0,
    ) -> None:
        """初始化 DirectoryWatchTriggerAdapter。"""

        if startup_timeout_seconds <= 0:
            raise InvalidRequestError("startup_timeout_seconds 必须大于 0")
        if stop_timeout_seconds <= 0:
            raise InvalidRequestError("stop_timeout_seconds 必须大于 0")
        self.startup_timeout_seconds = startup_timeout_seconds
        self.stop_timeout_seconds = stop_timeout_seconds
        self.dataset_storage_root_dir = Path(dataset_storage_root_dir).resolve()
        self._states: dict[str, _DirectoryWatchAdapterState] = {}
        self._lock = RLock()

    def start(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
    ) -> None:
        """启动一条目录监听 TriggerSource。"""

        if trigger_source.submit_mode != "async":
            raise InvalidRequestError(
                "directory-watch 只支持 async submit_mode",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "submit_mode": trigger_source.submit_mode,
                },
            )
        config = parse_directory_watch_trigger_config(
            trigger_source=trigger_source,
            dataset_storage_root_dir=self.dataset_storage_root_dir,
        )
        state = _DirectoryWatchAdapterState(
            trigger_source_id=trigger_source.trigger_source_id,
            config=config,
            stop_event=Event(),
            accumulator=DirectoryChangeWindowAccumulator(
                interval_seconds=config.min_trigger_interval_seconds,
                sample_limit=config.event_sample_limit,
            ),
        )
        with self._lock:
            if trigger_source.trigger_source_id in self._states:
                raise InvalidRequestError(
                    "Directory Watch TriggerSource 已经启动",
                    details={"trigger_source_id": trigger_source.trigger_source_id},
                )
            self._states[trigger_source.trigger_source_id] = state
        thread = Thread(
            target=self._watch_trigger_source,
            args=(trigger_source, event_handler, state),
            name=f"directory-watch-trigger-{trigger_source.trigger_source_id}",
            daemon=True,
        )
        state.thread = thread
        thread.start()
        if not state.startup_event.wait(timeout=self.startup_timeout_seconds):
            try:
                self.stop(trigger_source_id=trigger_source.trigger_source_id)
            except OperationTimeoutError:
                pass
            raise OperationTimeoutError(
                "等待 Directory Watch TriggerSource 启动超时",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "timeout_seconds": self.startup_timeout_seconds,
                },
            )
        if state.startup_error is not None:
            if state.thread is not None:
                state.thread.join(timeout=self.stop_timeout_seconds)
            with self._lock:
                if self._states.get(trigger_source.trigger_source_id) is state:
                    self._states.pop(trigger_source.trigger_source_id, None)
            raise ServiceConfigurationError(
                "Directory Watch TriggerSource 启动失败",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "directory_path": str(config.directory_path),
                    "error": state.startup_error,
                },
            )

    def stop(self, *, trigger_source_id: str) -> None:
        """停止监听并确认 watcher 线程完全退出。"""

        normalized_id = _require_stripped_text(trigger_source_id, "trigger_source_id")
        with self._lock:
            state = self._states.get(normalized_id)
        if state is None:
            return
        with state.state_lock:
            state.stop_requested = True
            state.stop_event.set()
        if state.thread is not None:
            state.thread.join(timeout=self.stop_timeout_seconds)
            if state.thread.is_alive():
                with state.state_lock:
                    state.last_error = "等待 Directory Watch watcher 线程停止超时"
                raise OperationTimeoutError(
                    state.last_error,
                    details={
                        "trigger_source_id": normalized_id,
                        "timeout_seconds": self.stop_timeout_seconds,
                        "submit_call_in_progress": state.submit_call_in_progress,
                    },
                )
        with self._lock:
            if self._states.get(normalized_id) is state:
                self._states.pop(normalized_id, None)

    def get_health(self, *, trigger_source_id: str) -> dict[str, object]:
        """读取目录监听 adapter 的有界健康状态。"""

        normalized_id = _require_stripped_text(trigger_source_id, "trigger_source_id")
        with self._lock:
            state = self._states.get(normalized_id)
        if state is None:
            return {
                "adapter_kind": self.adapter_kind,
                "source_scoped": True,
                "running": False,
                "watch_running": False,
                "trigger_source_id": normalized_id,
            }
        with state.state_lock:
            accumulator = state.accumulator
            error_count = (
                snapshot_safe_counter(state.submit_error_count)["value"]
                + snapshot_safe_counter(state.watch_error_count)["value"]
            )
            return {
                "adapter_kind": self.adapter_kind,
                "source_scoped": True,
                "running": state.running,
                "watch_running": state.running,
                "trigger_source_id": normalized_id,
                "directory_path": str(state.config.directory_path),
                "recursive": state.config.recursive,
                "include_hidden": state.config.include_hidden,
                "glob_pattern": state.config.glob_pattern,
                "extensions": list(state.config.extensions),
                "event_types": list(state.config.event_types),
                "configured_min_trigger_interval_seconds": (
                    state.config.min_trigger_interval_seconds
                ),
                "configured_event_sample_limit": state.config.event_sample_limit,
                "force_polling": state.config.force_polling,
                "poll_delay_ms": state.config.poll_delay_ms,
                "ignore_permission_denied": state.config.ignore_permission_denied,
                "submit_call_in_progress": state.submit_call_in_progress,
                "window_open": accumulator.is_open,
                "window_started_at": accumulator.window_started_at,
                "window_change_count": accumulator.total_change_count,
                "window_sample_count": accumulator.sample_count,
                "window_samples_truncated": accumulator.samples_truncated,
                "window_has_changes": accumulator.total_change_count > 0,
                "last_change_at": state.last_change_at,
                "last_submitted_at": state.last_submitted_at,
                "last_workflow_run_id": state.last_workflow_run_id,
                "last_submission_state": state.last_submission_state,
                "last_submit_duration_ms": state.last_submit_duration_ms,
                "max_submit_duration_ms": state.max_submit_duration_ms,
                "last_error": state.last_error,
                "request_count": snapshot_safe_counter(state.submitted_count)["value"],
                "success_count": snapshot_safe_counter(state.success_count)["value"],
                "error_count": error_count,
                "timeout_count": snapshot_safe_counter(state.timeout_count)["value"],
                **_counter_fields("watch_batch_count", state.watch_batch_count),
                **_counter_fields("submitted_count", state.submitted_count),
                **_counter_fields("coalesced_change_count", state.coalesced_change_count),
                **_counter_fields("truncated_window_count", state.truncated_window_count),
                **_counter_fields("late_window_count", state.late_window_count),
                **_counter_fields("submit_error_count", state.submit_error_count),
                **_counter_fields("watch_error_count", state.watch_error_count),
            }

    def _watch_trigger_source(
        self,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
        state: _DirectoryWatchAdapterState,
    ) -> None:
        """执行目录监听线程主循环。"""

        startup_completed = False
        try:
            for changes in watch(
                state.config.directory_path,
                watch_filter=None,
                debounce=_WATCH_DEBOUNCE_MS,
                step=_WATCH_STEP_MS,
                stop_event=state.stop_event,
                rust_timeout=_WATCH_TIMEOUT_MS,
                yield_on_timeout=True,
                recursive=state.config.recursive,
                force_polling=state.config.force_polling,
                poll_delay_ms=state.config.poll_delay_ms,
                ignore_permission_denied=state.config.ignore_permission_denied,
            ):
                if not startup_completed:
                    with state.state_lock:
                        state.running = True
                    state.startup_event.set()
                    startup_completed = True
                observed_monotonic = time.monotonic()
                observed_at = _now_isoformat()
                self._submit_due_window(
                    trigger_source=trigger_source,
                    event_handler=event_handler,
                    state=state,
                    now_monotonic=observed_monotonic,
                    window_finished_at=observed_at,
                )
                with state.state_lock:
                    if state.stop_requested:
                        break
                if changes:
                    self._apply_changes(
                        changes=changes,
                        state=state,
                        observed_monotonic=observed_monotonic,
                        observed_at=observed_at,
                    )
        except Exception as error:  # noqa: BLE001 - watcher 边界必须写入 health
            with state.state_lock:
                if not startup_completed:
                    state.startup_error = str(error).strip() or error.__class__.__name__
                state.last_error = str(error).strip() or error.__class__.__name__
                increment_safe_counter(state.watch_error_count)
            state.startup_event.set()
        finally:
            with state.state_lock:
                state.running = False
            state.startup_event.set()

    def _apply_changes(
        self,
        *,
        changes: set[tuple[Change, str]],
        state: _DirectoryWatchAdapterState,
        observed_monotonic: float,
        observed_at: str,
    ) -> None:
        """过滤一个 watcher 批次并写入当前有界窗口。"""

        matched_changes = self._iter_matched_changes(changes, state.config)
        with state.state_lock:
            if state.stop_requested:
                return
            increment_safe_counter(state.watch_batch_count)
            matched_count, opened_window = state.accumulator.add_batch(
                matched_changes,
                observed_monotonic=observed_monotonic,
                observed_at=observed_at,
            )
            if matched_count == 0:
                return
            state.last_change_at = observed_at
            coalesced_count = matched_count - 1 if opened_window else matched_count
            for _ in range(max(0, coalesced_count)):
                increment_safe_counter(state.coalesced_change_count)

    def _iter_matched_changes(
        self,
        changes: set[tuple[Change, str]],
        config: DirectoryWatchTriggerConfig,
    ):
        """单次遍历底层变化集合并生成通过公开过滤规则的事实。"""

        enabled_types = set(config.event_types)
        for change_kind, raw_path in changes:
            change_type = _CHANGE_NAME_BY_KIND.get(change_kind)
            if change_type is None or change_type not in enabled_types:
                continue
            resolve_existing_path = change_kind != Change.deleted
            candidate_path = Path(raw_path)
            if not matches_directory_candidate_path(
                candidate_path,
                directory_path=config.directory_path,
                recursive=config.recursive,
                include_hidden=config.include_hidden,
                glob_pattern=config.glob_pattern,
                extensions=config.extensions,
                resolve_existing_path=resolve_existing_path,
            ):
                continue
            normalized_path = (
                candidate_path.resolve()
                if resolve_existing_path
                else Path(os.path.abspath(candidate_path))
            )
            yield MatchedDirectoryChange(
                change_type=change_type,
                path=str(normalized_path),
                relative_path=Path(
                    os.path.relpath(normalized_path, config.directory_path)
                ).as_posix(),
                path_key=os.path.normcase(str(normalized_path)),
            )

    def _submit_due_window(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
        state: _DirectoryWatchAdapterState,
        now_monotonic: float,
        window_finished_at: str,
    ) -> None:
        """在停止线性化边界内取出到期快照并执行一次普通提交。"""

        with state.state_lock:
            if state.stop_requested or not state.accumulator.is_due(now_monotonic):
                return
            snapshot = state.accumulator.snapshot_and_reset(
                window_finished_at=window_finished_at
            )
            if snapshot is None:
                return
            if (
                now_monotonic - snapshot.window_deadline_monotonic
                > _LATE_WINDOW_THRESHOLD_SECONDS
            ):
                increment_safe_counter(state.late_window_count)
            state.submit_call_in_progress = True

        submit_started = time.perf_counter()
        try:
            raw_event, event_was_truncated = _build_raw_event(
                trigger_source=trigger_source,
                config=state.config,
                snapshot=snapshot,
            )
            if event_was_truncated:
                with state.state_lock:
                    increment_safe_counter(state.truncated_window_count)
            with state.state_lock:
                increment_safe_counter(state.submitted_count)
                state.last_submitted_at = raw_event.occurred_at
            result = event_handler.handle_trigger_event(
                trigger_source=trigger_source,
                raw_event=raw_event,
            )
            with state.state_lock:
                state.last_workflow_run_id = result.workflow_run_id
                state.last_submission_state = result.state
                if result.state in {"failed", "timed_out"}:
                    increment_safe_counter(state.submit_error_count)
                    if result.state == "timed_out":
                        increment_safe_counter(state.timeout_count)
                    state.last_error = result.error_message or result.state
                else:
                    increment_safe_counter(state.success_count)
                    state.last_error = None
        except Exception as error:  # noqa: BLE001 - 单次提交失败不能终止 watcher
            with state.state_lock:
                increment_safe_counter(state.submit_error_count)
                state.last_submission_state = "failed"
                state.last_error = str(error).strip() or error.__class__.__name__
        finally:
            duration_ms = (time.perf_counter() - submit_started) * 1000.0
            with state.state_lock:
                state.last_submit_duration_ms = round(duration_ms, 3)
                state.max_submit_duration_ms = max(
                    state.max_submit_duration_ms,
                    state.last_submit_duration_ms,
                )
                state.submit_call_in_progress = False


def _build_raw_event(
    *,
    trigger_source: WorkflowTriggerSource,
    config: DirectoryWatchTriggerConfig,
    snapshot: DirectoryChangeWindowSnapshot,
) -> tuple[RawTriggerEvent, bool]:
    """构造并收敛到 64 KiB 以内的标准目录变化事件。"""

    event_id = f"directory-watch-event-{uuid4().hex}"
    samples = [
        {
            "observed_change_types": list(sample.observed_change_types),
            "path": sample.path,
            "relative_path": sample.relative_path,
            "observed_at": sample.observed_at,
            "observed_sequence": sample.observed_sequence,
        }
        for sample in snapshot.samples
    ]
    samples_truncated = snapshot.samples_truncated
    while True:
        event_value = DirectoryChangeEventContract.model_validate(
            {
                "event_id": event_id,
                "trigger_source_id": trigger_source.trigger_source_id,
                "workflow_runtime_id": trigger_source.workflow_runtime_id,
                "window_started_at": snapshot.window_started_at,
                "window_finished_at": snapshot.window_finished_at,
                "min_trigger_interval_seconds": config.min_trigger_interval_seconds,
                "directory": {
                    "path": str(config.directory_path),
                    "recursive": config.recursive,
                    "glob_pattern": config.glob_pattern,
                    "extensions": list(config.extensions),
                },
                "change_counts": {
                    "created": snapshot.created_count,
                    "modified": snapshot.modified_count,
                    "deleted": snapshot.deleted_count,
                    "total": snapshot.total_change_count,
                },
                "samples": samples,
                "sample_limit": config.event_sample_limit,
                "sample_count": len(samples),
                "samples_truncated": samples_truncated,
            }
        ).model_dump(mode="json")
        raw_event = RawTriggerEvent(
            payload={"directory_event_value": {"value": event_value}},
            event_id=event_id,
            trace_id=event_id,
            occurred_at=snapshot.window_finished_at,
            metadata={
                "transport": "directory-watch",
                "directory_path": str(config.directory_path),
            },
        )
        if _raw_event_size_bytes(raw_event) <= DIRECTORY_EVENT_MAX_BYTES:
            return raw_event, samples_truncated
        if samples:
            samples.pop()
            samples_truncated = True
            continue
        raise InvalidRequestError(
            "Directory Watch 事件超过 64 KiB 上限",
            details={
                "trigger_source_id": trigger_source.trigger_source_id,
                "max_bytes": DIRECTORY_EVENT_MAX_BYTES,
            },
        )


def _raw_event_size_bytes(raw_event: RawTriggerEvent) -> int:
    """返回完整 RawTriggerEvent 的紧凑 UTF-8 JSON 字节数。"""

    payload = {
        "payload": raw_event.payload,
        "event_id": raw_event.event_id,
        "trace_id": raw_event.trace_id,
        "occurred_at": raw_event.occurred_at,
        "metadata": raw_event.metadata,
    }
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _counter_fields(prefix: str, counter: SafeCounterState) -> dict[str, int]:
    """把 SafeCounterState 转成统一 health 字段。"""

    snapshot = snapshot_safe_counter(counter)
    return {
        prefix: snapshot["value"],
        f"{prefix}_rollover_count": snapshot["rollover_count"],
    }


def _now_isoformat() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized_value
