"""directory-watch 新变化通知契约与有界聚合测试。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

import pytest
from pydantic import ValidationError
from backend.contracts.workflows import (
    DirectoryChangeEventContract,
    DirectoryWatchTransportConfigContract,
    TriggerResultContract,
)
from backend.service.application.errors import InvalidRequestError, OperationTimeoutError
from backend.service.application.workflows.trigger_sources.trigger_source_service import (
    _apply_directory_watch_default_mapping,
)
from backend.service.application.workflows.trigger_sources.protocol_adapter import (
    WorkflowTriggerDispatchResult,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.integrations.directory.directory_change_window import (
    DirectoryChangeWindowAccumulator,
    DirectoryChangeWindowSnapshot,
    DirectoryChangeSampleSnapshot,
    MatchedDirectoryChange,
)
from backend.service.infrastructure.integrations.directory.directory_watch_trigger_adapter import (
    DIRECTORY_EVENT_MAX_BYTES,
    DirectoryWatchTriggerAdapter,
    _build_raw_event,
    _raw_event_size_bytes,
)
from backend.service.infrastructure.integrations.directory._directory_trigger_support import (
    DirectoryWatchTriggerConfig,
)


def test_directory_watch_transport_config_normalizes_public_fields(tmp_path: Path) -> None:
    """验证目录监听配置只有变化通知所需字段。"""

    contract = DirectoryWatchTransportConfigContract.model_validate(
        {
            "directory_path": str(tmp_path),
            "extensions": ["PNG", ".json", "png"],
            "event_types": ["deleted", "created"],
        }
    )

    assert contract.extensions == (".json", ".png")
    assert contract.event_types == ("created", "deleted")
    assert contract.min_trigger_interval_seconds == 3.0
    assert contract.event_sample_limit == 10
    with pytest.raises(ValidationError):
        DirectoryWatchTransportConfigContract.model_validate(
            {"directory_path": "relative", "min_trigger_interval_seconds": 3.0}
        )
    with pytest.raises(ValidationError):
        DirectoryWatchTransportConfigContract.model_validate(
            {"directory_path": str(tmp_path), "batch_size": 10}
        )
    with pytest.raises(ValidationError):
        DirectoryWatchTransportConfigContract.model_validate(
            {"directory_path": str(tmp_path), "event_sample_limit": True}
        )


def test_directory_change_event_contract_rejects_inconsistent_counts() -> None:
    """验证公开目录事件拒绝计数不一致。"""

    with pytest.raises(ValidationError):
        DirectoryChangeEventContract.model_validate(
            {
                "event_id": "directory-watch-event-1",
                "trigger_source_id": "directory-watch-runtime-1-a1b2c3d4",
                "workflow_runtime_id": "workflow-runtime-1",
                "window_started_at": "2026-09-03T00:00:00Z",
                "window_finished_at": "2026-09-03T00:00:03Z",
                "min_trigger_interval_seconds": 3.0,
                "directory": {
                    "path": "W:\\results",
                    "recursive": False,
                    "glob_pattern": "*",
                    "extensions": [],
                },
                "change_counts": {
                    "created": 1,
                    "modified": 0,
                    "deleted": 0,
                    "total": 2,
                },
                "samples": [],
                "sample_limit": 10,
                "sample_count": 0,
                "samples_truncated": False,
            }
        )


def test_directory_change_window_keeps_only_bounded_recent_samples() -> None:
    """验证一万条变化不会留下超过样本上限的路径状态。"""

    accumulator = DirectoryChangeWindowAccumulator(
        interval_seconds=3.0,
        sample_limit=10,
    )
    changes = (
        MatchedDirectoryChange(
            change_type="created",
            path=f"W:\\results\\item-{index:05d}.json",
            relative_path=f"item-{index:05d}.json",
            path_key=f"w:\\results\\item-{index:05d}.json",
        )
        for index in range(10_000)
    )

    matched_count, opened = accumulator.add_batch(
        changes,
        observed_monotonic=100.0,
        observed_at="2026-09-03T00:00:00Z",
    )
    snapshot = accumulator.snapshot_and_reset(
        window_finished_at="2026-09-03T00:00:03Z"
    )

    assert matched_count == 10_000
    assert opened is True
    assert snapshot is not None
    assert snapshot.total_change_count == 10_000
    assert len(snapshot.samples) == 10
    assert snapshot.samples_truncated is True
    assert snapshot.samples[0].relative_path == "item-09999.json"
    assert snapshot.samples[-1].relative_path == "item-09990.json"
    assert accumulator.sample_count == 0
    assert accumulator.total_change_count == 0


def test_directory_change_window_replaces_same_path_batch_types() -> None:
    """验证同一路径后续批次会替换变化类型并移动到最新位置。"""

    accumulator = DirectoryChangeWindowAccumulator(
        interval_seconds=3.0,
        sample_limit=2,
    )
    path = "W:\\results\\same.json"
    accumulator.add_batch(
        (
            MatchedDirectoryChange("created", path, "same.json", path.lower()),
            MatchedDirectoryChange("modified", path, "same.json", path.lower()),
        ),
        observed_monotonic=1.0,
        observed_at="2026-09-03T00:00:00Z",
    )
    accumulator.add_batch(
        (MatchedDirectoryChange("deleted", path, "same.json", path.lower()),),
        observed_monotonic=2.0,
        observed_at="2026-09-03T00:00:01Z",
    )
    snapshot = accumulator.snapshot_and_reset(
        window_finished_at="2026-09-03T00:00:03Z"
    )

    assert snapshot is not None
    assert snapshot.total_change_count == 3
    assert len(snapshot.samples) == 1
    assert snapshot.samples[0].observed_change_types == ("deleted",)


def test_directory_raw_event_shrinks_oldest_samples_to_capacity(tmp_path: Path) -> None:
    """验证目录事件按最旧样本优先缩减并保持合法 JSON。"""

    long_tail = "x" * 2000
    samples = tuple(
        DirectoryChangeSampleSnapshot(
            observed_change_types=("created",),
            path=str(tmp_path / f"{index:03d}-{long_tail}.json"),
            relative_path=f"{index:03d}-{long_tail}.json",
            observed_at="2026-09-03T00:00:01Z",
            observed_sequence=index + 1,
        )
        for index in reversed(range(100))
    )
    snapshot = DirectoryChangeWindowSnapshot(
        window_started_at="2026-09-03T00:00:00Z",
        window_finished_at="2026-09-03T00:00:03Z",
        window_deadline_monotonic=3.0,
        created_count=100,
        modified_count=0,
        deleted_count=0,
        samples=samples,
        samples_truncated=False,
    )

    raw_event, was_truncated = _build_raw_event(
        trigger_source=_build_trigger_source(tmp_path),
        config=_build_config(tmp_path, sample_limit=100),
        snapshot=snapshot,
    )
    event_value = raw_event.payload["directory_event_value"]["value"]

    assert was_truncated is True
    assert _raw_event_size_bytes(raw_event) <= DIRECTORY_EVENT_MAX_BYTES
    assert event_value["sample_count"] < 100
    assert event_value["samples"][0]["observed_sequence"] == 100
    json.dumps(event_value)


def test_directory_watch_adapter_submits_created_and_deleted_windows(
    tmp_path: Path,
) -> None:
    """验证真实 watcher 分窗口提交新增和删除通知。"""

    trigger_source = _build_trigger_source(tmp_path)
    adapter = DirectoryWatchTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )
    handler = _CapturingEventHandler()
    adapter.start(trigger_source=trigger_source, event_handler=handler)
    try:
        target = tmp_path / "watched" / "sample.png"
        target.write_bytes(b"image")
        _wait_for_submission_count(handler, 1)
        target.unlink()
        _wait_for_submission_count(handler, 2)
        health = adapter.get_health(trigger_source_id=trigger_source.trigger_source_id)
    finally:
        adapter.stop(trigger_source_id=trigger_source.trigger_source_id)

    first_event = handler.events[0].payload["directory_event_value"]["value"]
    second_event = handler.events[1].payload["directory_event_value"]["value"]
    assert first_event["change_counts"]["created"] >= 1
    assert second_event["change_counts"]["deleted"] >= 1
    assert health["submitted_count"] == 2
    assert health["window_sample_count"] <= 10
    assert "checkpoint_path" not in health


def test_directory_watch_adapter_rejects_old_batch_config(tmp_path: Path) -> None:
    """验证开发期不静默兼容旧 file-batch 配置。"""

    watched_dir = tmp_path / "watched"
    watched_dir.mkdir()
    source = _build_trigger_source(tmp_path)
    source = WorkflowTriggerSource(
        **{
            **source.__dict__,
            "transport_config": {
                "directory_path": str(watched_dir),
                "batch_size": 10,
            },
        }
    )
    adapter = DirectoryWatchTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data")
    )

    with pytest.raises(InvalidRequestError):
        adapter.start(trigger_source=source, event_handler=_CapturingEventHandler())


def test_directory_watch_default_mapping_only_targets_optional_request_json() -> None:
    """验证自动映射不猜测其他 binding 且不覆盖手动规则。"""

    contract = {
        "inputs": [
            {
                "binding_id": "request_json",
                "payload_type_id": "value.v1",
                "required": False,
            },
            {
                "binding_id": "request_text",
                "payload_type_id": "text.v1",
                "required": False,
            },
        ]
    }
    mapping: dict[str, object] = {}

    _apply_directory_watch_default_mapping(
        contract=contract,
        trigger_kind="directory-watch",
        input_binding_mapping=mapping,
    )

    assert mapping == {
        "request_json": {
            "source": "payload.directory_event_value",
            "required": False,
            "payload_type_id": "value.v1",
            "metadata": {"inferred": True, "source": "directory-watch"},
        }
    }
    manual_mapping = {
        "request_json": {
            "source": "payload.custom",
            "required": False,
        }
    }
    _apply_directory_watch_default_mapping(
        contract=contract,
        trigger_kind="directory-watch",
        input_binding_mapping=manual_mapping,
    )
    assert manual_mapping["request_json"]["source"] == "payload.custom"


def test_directory_watch_stop_timeout_preserves_managed_state(tmp_path: Path) -> None:
    """验证提交调用未退出时 stop 明确失败且不会遗失线程句柄。"""

    trigger_source = _build_trigger_source(tmp_path)
    handler = _BlockingEventHandler()
    adapter = DirectoryWatchTriggerAdapter(
        dataset_storage_root_dir=str(tmp_path / "data"),
        stop_timeout_seconds=0.05,
    )
    adapter.start(trigger_source=trigger_source, event_handler=handler)
    target = tmp_path / "watched" / "blocking.png"
    target.write_bytes(b"image")
    assert handler.entered.wait(timeout=3.0)

    with pytest.raises(OperationTimeoutError) as error_info:
        adapter.stop(trigger_source_id=trigger_source.trigger_source_id)
    assert "停止超时" in str(error_info.value)
    health = adapter.get_health(trigger_source_id=trigger_source.trigger_source_id)
    assert health["submit_call_in_progress"] is True

    handler.release.set()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and health["submit_call_in_progress"]:
        time.sleep(0.02)
        health = adapter.get_health(trigger_source_id=trigger_source.trigger_source_id)
    adapter.stop(trigger_source_id=trigger_source.trigger_source_id)
    assert adapter.get_health(trigger_source_id=trigger_source.trigger_source_id)["running"] is False


def _build_config(tmp_path: Path, *, sample_limit: int = 10) -> DirectoryWatchTriggerConfig:
    """构造事件容量测试使用的目录配置。"""

    return DirectoryWatchTriggerConfig(
        directory_path=tmp_path,
        recursive=False,
        include_hidden=False,
        glob_pattern="*",
        extensions=(),
        event_types=("created", "modified", "deleted"),
        min_trigger_interval_seconds=1.0,
        event_sample_limit=sample_limit,
        force_polling=False,
        poll_delay_ms=300,
        ignore_permission_denied=False,
    )


def _build_trigger_source(tmp_path: Path) -> WorkflowTriggerSource:
    """构造测试使用的目录 TriggerSource。"""

    watched_dir = tmp_path / "watched"
    watched_dir.mkdir(exist_ok=True)
    return WorkflowTriggerSource(
        trigger_source_id="directory-watch-workflow-runtime-1-a1b2c3d4",
        project_id="project-1",
        display_name="Directory Watch",
        trigger_kind="directory-watch",
        workflow_runtime_id="workflow-runtime-1",
        submit_mode="async",
        enabled=True,
        desired_state="running",
        observed_state="running",
        transport_config={
            "directory_path": str(watched_dir),
            "extensions": ["png"],
            "event_types": ["created", "modified", "deleted"],
            "min_trigger_interval_seconds": 1.0,
            "event_sample_limit": 10,
            "force_polling": False,
            "poll_delay_ms": 300,
            "ignore_permission_denied": False,
        },
        input_binding_mapping={
            "request_json": {
                "source": "payload.directory_event_value",
                "required": False,
                "payload_type_id": "value.v1",
            }
        },
        result_mapping={"result_bindings": []},
        ack_policy="ack-after-run-created",
        result_mode="event-only",
        created_at="2026-09-03T00:00:00Z",
        updated_at="2026-09-03T00:00:00Z",
    )


def _wait_for_submission_count(handler: _CapturingEventHandler, count: int) -> None:
    """等待真实 watcher 完成指定次数提交。"""

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if len(handler.events) >= count:
            return
        time.sleep(0.02)
    raise AssertionError(f"等待目录 Trigger 提交超时: {len(handler.events)} < {count}")


@dataclass
class _CapturingEventHandler:
    """记录目录 adapter 原始事件的测试替身。"""

    events: list[object] = field(default_factory=list)

    def handle_trigger_event(self, *, trigger_source, raw_event):
        """记录事件并返回 async accepted 回执。"""

        self.events.append(raw_event)
        return WorkflowTriggerDispatchResult(
            trigger_result=TriggerResultContract(
                trigger_source_id=trigger_source.trigger_source_id,
                event_id=raw_event.event_id,
                state="accepted",
                workflow_run_id=f"workflow-run-{len(self.events)}",
            )
        )


@dataclass
class _BlockingEventHandler:
    """让本地提交调用停留在 stop 竞态中的测试替身。"""

    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)

    def handle_trigger_event(self, *, trigger_source, raw_event):
        """等待测试释放后返回 accepted。"""

        self.entered.set()
        self.release.wait(timeout=5.0)
        return WorkflowTriggerDispatchResult(
            trigger_result=TriggerResultContract(
                trigger_source_id=trigger_source.trigger_source_id,
                event_id=raw_event.event_id,
                state="accepted",
                workflow_run_id="workflow-run-blocking",
            )
        )
