"""目录轮询 TriggerSource adapter。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread

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
    DirectoryPollTriggerConfig,
    build_checkpoint_path,
    build_record_identity_key,
    parse_directory_poll_trigger_config,
    scan_directory_records,
)


CHECKPOINT_FORMAT_ID = "amvision.directory-poll-checkpoint.v1"


@dataclass
class _DirectoryPollAdapterState:
    """描述一条 directory-poll TriggerSource 的运行状态。"""

    trigger_source_id: str
    config: DirectoryPollTriggerConfig
    stop_event: Event
    startup_event: Event = field(default_factory=Event)
    thread: Thread | None = None
    running: bool = False
    poll_count: SafeCounterState = field(default_factory=SafeCounterState)
    submitted_count: SafeCounterState = field(default_factory=SafeCounterState)
    error_count: SafeCounterState = field(default_factory=SafeCounterState)
    timeout_count: SafeCounterState = field(default_factory=SafeCounterState)
    last_error: str | None = None
    startup_error: str | None = None
    last_scan_at: str | None = None
    last_emit_at: str | None = None
    last_result_state: str | None = None
    last_visible_count: int = 0
    last_new_candidate_count: int = 0
    last_batch_file_count: int = 0
    sequence_id: int = 0
    known_identity_keys: set[str] = field(default_factory=set)


class DirectoryPollTriggerAdapter:
    """按固定周期扫描目录中的新文件并提交 WorkflowRun。"""

    adapter_kind = "directory-poll"

    def __init__(
        self,
        *,
        dataset_storage_root_dir: str,
        startup_timeout_seconds: float = 1.0,
    ) -> None:
        """初始化 DirectoryPollTriggerAdapter。"""

        if startup_timeout_seconds <= 0:
            raise InvalidRequestError("startup_timeout_seconds 必须大于 0")
        self.startup_timeout_seconds = startup_timeout_seconds
        self.dataset_storage_root_dir = Path(dataset_storage_root_dir).resolve()
        self.dataset_storage_root_dir.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, _DirectoryPollAdapterState] = {}
        self._lock = RLock()

    def start(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
    ) -> None:
        """启动一条目录轮询 TriggerSource。"""

        if trigger_source.submit_mode != "async":
            raise InvalidRequestError(
                "directory-poll 当前只支持 async submit_mode",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "submit_mode": trigger_source.submit_mode,
                },
            )
        config = parse_directory_poll_trigger_config(
            trigger_source=trigger_source,
            dataset_storage_root_dir=self.dataset_storage_root_dir,
        )
        checkpoint_state = _load_checkpoint_state(
            checkpoint_path=config.checkpoint_path,
            trigger_source=trigger_source,
        )
        state = _DirectoryPollAdapterState(
            trigger_source_id=trigger_source.trigger_source_id,
            config=config,
            stop_event=Event(),
            sequence_id=checkpoint_state["sequence_id"],
            known_identity_keys=set(checkpoint_state["seen_identity_keys"]),
        )
        with self._lock:
            if trigger_source.trigger_source_id in self._states:
                raise InvalidRequestError(
                    "Directory Poll TriggerSource 已经启动",
                    details={"trigger_source_id": trigger_source.trigger_source_id},
                )
            self._states[trigger_source.trigger_source_id] = state
        thread = Thread(
            target=self._poll_trigger_source,
            args=(trigger_source, event_handler, state),
            name=f"directory-poll-trigger-{trigger_source.trigger_source_id}",
            daemon=True,
        )
        state.thread = thread
        thread.start()
        if not state.startup_event.wait(timeout=self.startup_timeout_seconds):
            self.stop(trigger_source_id=trigger_source.trigger_source_id)
            raise OperationTimeoutError(
                "等待 Directory Poll TriggerSource 启动超时",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "timeout_seconds": self.startup_timeout_seconds,
                },
            )
        if state.startup_error is not None:
            with self._lock:
                self._states.pop(trigger_source.trigger_source_id, None)
            raise ServiceConfigurationError(
                "Directory Poll TriggerSource 启动失败",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "directory_path": str(config.directory_path),
                    "error": state.startup_error,
                },
            )

    def stop(self, *, trigger_source_id: str) -> None:
        """停止一条目录轮询 TriggerSource。"""

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._lock:
            state = self._states.pop(normalized_trigger_source_id, None)
        if state is None:
            return
        state.stop_event.set()
        if state.thread is not None:
            state.thread.join(timeout=2.0)

    def get_health(self, *, trigger_source_id: str) -> dict[str, object]:
        """读取目录轮询 adapter 的健康状态。"""

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
                "checkpoint_path": str(
                    build_checkpoint_path(
                        self.dataset_storage_root_dir,
                        normalized_trigger_source_id,
                    )
                ),
            }
        return {
            "adapter_kind": self.adapter_kind,
            "running": state.running,
            "trigger_source_id": normalized_trigger_source_id,
            "directory_path": str(state.config.directory_path),
            "recursive": state.config.recursive,
            "include_hidden": state.config.include_hidden,
            "glob_pattern": state.config.glob_pattern,
            "extensions": list(state.config.extensions),
            "sort_by": state.config.sort_by,
            "descending": state.config.descending,
            "dedupe_by": state.config.dedupe_by,
            "batch_size": state.config.batch_size,
            "scan_interval_seconds": state.config.scan_interval_seconds,
            "min_stable_age_seconds": state.config.min_stable_age_seconds,
            "persist_checkpoint": state.config.persist_checkpoint,
            "checkpoint_path": str(state.config.checkpoint_path),
            "last_scan_at": state.last_scan_at,
            "last_emit_at": state.last_emit_at,
            "last_result_state": state.last_result_state,
            "last_error": state.last_error,
            "last_visible_count": state.last_visible_count,
            "last_new_candidate_count": state.last_new_candidate_count,
            "last_batch_file_count": state.last_batch_file_count,
            "sequence_id": state.sequence_id,
            "known_identity_count": len(state.known_identity_keys),
            **_counter_fields("poll_count", state.poll_count),
            **_counter_fields("submitted_count", state.submitted_count),
            **_counter_fields("error_count", state.error_count),
            **_counter_fields("timeout_count", state.timeout_count),
        }

    def _poll_trigger_source(
        self,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
        state: _DirectoryPollAdapterState,
    ) -> None:
        """执行目录轮询线程主循环。"""

        try:
            state.running = True
            state.startup_event.set()
            while not state.stop_event.is_set():
                try:
                    self._poll_once(
                        trigger_source=trigger_source,
                        event_handler=event_handler,
                        state=state,
                    )
                except Exception as error:  # pragma: no cover - 线程异常由 health 暴露
                    _record_adapter_error(state, error)
                if state.stop_event.wait(state.config.scan_interval_seconds):
                    break
        except Exception as error:  # pragma: no cover - 启动阶段异常极少
            state.startup_error = str(error).strip() or error.__class__.__name__
            state.startup_event.set()
            _record_adapter_error(state, error)
        finally:
            state.running = False

    def _poll_once(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
        state: _DirectoryPollAdapterState,
    ) -> None:
        """执行一次目录扫描与事件提交。"""

        records, scan_summary = scan_directory_records(
            state.config,
            current_time_seconds=time.time(),
        )
        increment_safe_counter(state.poll_count)
        state.last_scan_at = _now_isoformat()
        state.last_visible_count = len(records)

        current_identity_keys = {
            build_record_identity_key(record, dedupe_by=state.config.dedupe_by)
            for record in records
        }
        if state.known_identity_keys:
            retained_identity_keys = state.known_identity_keys.intersection(
                current_identity_keys
            )
            if retained_identity_keys != state.known_identity_keys:
                state.known_identity_keys = retained_identity_keys
                self._save_checkpoint_safely(state)

        new_records = [
            record
            for record in records
            if build_record_identity_key(record, dedupe_by=state.config.dedupe_by)
            not in state.known_identity_keys
        ]
        state.last_new_candidate_count = len(new_records)
        if not new_records:
            state.last_batch_file_count = 0
            return

        batch_records = new_records[: state.config.batch_size]
        next_sequence_id = state.sequence_id + 1
        raw_event = _build_raw_event(
            trigger_source=trigger_source,
            state=state,
            scan_summary=scan_summary,
            batch_records=batch_records,
            sequence_id=next_sequence_id,
        )
        result = event_handler.handle_trigger_event(
            trigger_source=trigger_source,
            raw_event=raw_event,
        )
        increment_safe_counter(state.submitted_count)
        state.last_result_state = result.state
        if result.state == "timed_out":
            increment_safe_counter(state.timeout_count)
            state.last_error = result.error_message
            return
        if result.state == "failed":
            increment_safe_counter(state.error_count)
            state.last_error = result.error_message
            return

        state.last_error = None
        state.sequence_id = next_sequence_id
        state.last_emit_at = raw_event.occurred_at
        state.last_batch_file_count = len(batch_records)
        for record in batch_records:
            state.known_identity_keys.add(
                build_record_identity_key(record, dedupe_by=state.config.dedupe_by)
            )
        self._save_checkpoint_safely(state)

    def _save_checkpoint_safely(self, state: _DirectoryPollAdapterState) -> None:
        """尽量保存 checkpoint，但不让写盘失败导致当前线程退出。"""

        if not state.config.persist_checkpoint:
            return
        try:
            _save_checkpoint_state(
                checkpoint_path=state.config.checkpoint_path,
                trigger_source_id=state.trigger_source_id,
                sequence_id=state.sequence_id,
                seen_identity_keys=state.known_identity_keys,
            )
        except Exception as error:  # pragma: no cover - 保护长跑线程
            increment_safe_counter(state.error_count)
            state.last_error = str(error).strip() or error.__class__.__name__


def _build_raw_event(
    *,
    trigger_source: WorkflowTriggerSource,
    state: _DirectoryPollAdapterState,
    scan_summary: dict[str, object],
    batch_records: list[dict[str, object]],
    sequence_id: int,
) -> RawTriggerEvent:
    """把当前批次文件组装成标准化原始事件。"""

    occurred_at = _now_isoformat()
    primary_file = batch_records[0] if batch_records else None
    primary_file_path = (
        str(primary_file.get("path"))
        if isinstance(primary_file, dict) and isinstance(primary_file.get("path"), str)
        else None
    )
    file_paths = [
        str(item.get("path"))
        for item in batch_records
        if isinstance(item.get("path"), str)
    ]
    batch_id = f"{trigger_source.trigger_source_id}:{sequence_id}"
    payload: dict[str, object] = {
        "directory_path": str(state.config.directory_path),
        "directory_path_value": {"value": str(state.config.directory_path)},
        "files": batch_records,
        "files_value": {"value": batch_records},
        "file_paths": file_paths,
        "file_paths_value": {"value": file_paths},
        "file_count": len(batch_records),
        "file_count_value": {"value": len(batch_records)},
        "primary_file": primary_file,
        "scan_summary": {
            **scan_summary,
            "new_candidate_count": state.last_new_candidate_count,
            "emitted_batch_file_count": len(batch_records),
            "sequence_id": sequence_id,
        },
        "sequence_id": sequence_id,
        "sequence_id_value": {"value": sequence_id},
        "batch_id": batch_id,
        "batch_id_value": {"value": batch_id},
    }
    if primary_file_path is not None:
        payload["primary_file_path"] = primary_file_path
        payload["primary_file_path_value"] = {"value": primary_file_path}
    return RawTriggerEvent(
        payload=payload,
        event_id=f"directory-poll-{trigger_source.trigger_source_id}-{sequence_id}",
        trace_id=f"directory-poll-{trigger_source.trigger_source_id}-{sequence_id}",
        occurred_at=occurred_at,
        metadata={
            "transport": "directory-poll",
            "directory_path": str(state.config.directory_path),
            "batch_id": batch_id,
            "file_count": len(batch_records),
        },
    )


def _load_checkpoint_state(
    *,
    checkpoint_path: Path,
    trigger_source: WorkflowTriggerSource,
) -> dict[str, object]:
    """读取目录轮询 checkpoint。"""

    if not checkpoint_path.is_file():
        return {"sequence_id": 0, "seen_identity_keys": []}
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001
        raise ServiceConfigurationError(
            "Directory Poll checkpoint 读取失败",
            details={
                "trigger_source_id": trigger_source.trigger_source_id,
                "checkpoint_path": str(checkpoint_path),
                "error": str(error).strip() or error.__class__.__name__,
            },
        ) from error
    if not isinstance(payload, dict):
        raise ServiceConfigurationError(
            "Directory Poll checkpoint 格式不正确",
            details={
                "trigger_source_id": trigger_source.trigger_source_id,
                "checkpoint_path": str(checkpoint_path),
            },
        )
    if payload.get("format_id") != CHECKPOINT_FORMAT_ID:
        raise ServiceConfigurationError(
            "Directory Poll checkpoint format_id 不受支持",
            details={
                "trigger_source_id": trigger_source.trigger_source_id,
                "checkpoint_path": str(checkpoint_path),
                "format_id": payload.get("format_id"),
            },
        )
    stored_trigger_source_id = payload.get("trigger_source_id")
    if stored_trigger_source_id != trigger_source.trigger_source_id:
        raise ServiceConfigurationError(
            "Directory Poll checkpoint 与当前 trigger_source_id 不匹配",
            details={
                "trigger_source_id": trigger_source.trigger_source_id,
                "checkpoint_path": str(checkpoint_path),
                "stored_trigger_source_id": stored_trigger_source_id,
            },
        )
    sequence_id = payload.get("sequence_id", 0)
    seen_identity_keys = payload.get("seen_identity_keys", [])
    if isinstance(sequence_id, bool) or not isinstance(sequence_id, int) or sequence_id < 0:
        raise ServiceConfigurationError(
            "Directory Poll checkpoint.sequence_id 非法",
            details={
                "trigger_source_id": trigger_source.trigger_source_id,
                "checkpoint_path": str(checkpoint_path),
            },
        )
    if not isinstance(seen_identity_keys, list) or any(
        not isinstance(item, str) or not item.strip() for item in seen_identity_keys
    ):
        raise ServiceConfigurationError(
            "Directory Poll checkpoint.seen_identity_keys 非法",
            details={
                "trigger_source_id": trigger_source.trigger_source_id,
                "checkpoint_path": str(checkpoint_path),
            },
        )
    return {
        "sequence_id": sequence_id,
        "seen_identity_keys": [item.strip() for item in seen_identity_keys],
    }


def _save_checkpoint_state(
    *,
    checkpoint_path: Path,
    trigger_source_id: str,
    sequence_id: int,
    seen_identity_keys: set[str],
) -> None:
    """把目录轮询状态写入本地 checkpoint。"""

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_payload = {
        "format_id": CHECKPOINT_FORMAT_ID,
        "trigger_source_id": trigger_source_id,
        "adapter_kind": "directory-poll",
        "sequence_id": sequence_id,
        "seen_identity_keys": sorted(seen_identity_keys),
        "updated_at": _now_isoformat(),
    }
    checkpoint_path.write_text(
        json.dumps(checkpoint_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _counter_fields(prefix: str, counter: SafeCounterState) -> dict[str, int]:
    """把 SafeCounterState 转成统一 health 字段。"""

    snapshot = snapshot_safe_counter(counter)
    return {
        prefix: snapshot["value"],
        f"{prefix}_rollover_count": snapshot["rollover_count"],
    }


def _record_adapter_error(state: _DirectoryPollAdapterState, error: Exception) -> None:
    """记录目录轮询线程中的异常。"""

    increment_safe_counter(state.error_count)
    state.last_error = str(error).strip() or error.__class__.__name__


def _now_isoformat() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized_value
