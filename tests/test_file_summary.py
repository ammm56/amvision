"""增量归约、检查点重建和独立执行计数测试。"""

from contextlib import nullcontext
from uuid import uuid4

import pytest

from backend.nodes.core_nodes.support.file_summary import summarize
from backend.service.application.runtime.io.jsonl import append_record
from backend.service.application.errors import InvalidRequestError

RULES = [
    {"output_key": "total", "source_path": "delta.total", "operation": "sum"},
    {"output_key": "ng", "source_path": "delta.ng", "operation": "sum"},
]


def test_incremental_checkpoint_restart_rebuild(tmp_path):
    """分批、重复调用、检查点损坏重建的累计与全量一致。"""
    path, state = tmp_path / "r.jsonl", tmp_path / "state.json"
    for n in range(5):
        append_record(path, {"delta": {"total": 24, "ng": n}}, operation=uuid4().hex)

    def run(**options):
        return summarize(path, state, reducers=RULES, lock=nullcontext(True), **options)

    first = run(max_records=2)
    assert first["status"] == "loading"
    assert first["totals"] == {"total": 48, "ng": 1}
    final = run()
    assert final["totals"] == {"total": 120, "ng": 10}
    assert final == run()
    state.write_bytes(b"broken")
    assert run()["totals"] == final["totals"]
    append_record(path, {"delta": {"total": 24, "ng": 2}}, operation=uuid4().hex)
    assert run()["totals"] == {"total": 144, "ng": 12}


def test_zero_missing_invalid_numbers_and_lock_conflict(tmp_path):
    """空源明确返回 empty，错误不发布检查点。"""
    path, state = tmp_path / "r.jsonl", tmp_path / "state.json"
    assert (
        summarize(
            path, state, reducers=RULES, lock=nullcontext(True), allow_missing=True
        )["status"]
        == "empty"
    )
    append_record(path, {"delta": {"total": 24, "ng": 1}}, operation="one")
    with pytest.raises(InvalidRequestError, match="更新"):
        summarize(path, state, reducers=RULES, lock=nullcontext(False))
    assert not state.exists()
    append_record(path, {"delta": {"total": True, "ng": 1}}, operation="two")
    with pytest.raises(InvalidRequestError, match="数值"):
        summarize(path, state, reducers=RULES, lock=nullcontext(True))
    assert not state.exists()


def test_checkpoint_failure_retry_filter_and_rule_change(tmp_path, monkeypatch):
    """提交失败不发布新游标；规则变更从权威日志有界重建。"""
    from backend.nodes.core_nodes.support import file_summary as summary

    path, state = tmp_path / "r.jsonl", tmp_path / "state.json"
    for index in range(3):
        append_record(path, {"delta": {"total": 80, "ng": index}}, operation=str(index))
    write = summary.atomic_write_bytes

    def broken(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(summary, "atomic_write_bytes", broken)
    with pytest.raises(OSError, match="disk failure"):
        summarize(path, state, reducers=RULES, lock=nullcontext(True))
    assert not state.exists()
    monkeypatch.setattr(summary, "atomic_write_bytes", write)
    assert (
        summarize(path, state, reducers=RULES, lock=nullcontext(True))["totals"][
            "total"
        ]
        == 240
    )
    filtered = summarize(
        path,
        state,
        reducers=RULES,
        lock=nullcontext(True),
        condition={"operator": "gt", "path": "delta.ng", "right": 0},
        max_records=1,
    )
    assert filtered["status"] == "loading"
    assert filtered["source"]["complete"] is False
    final = summarize(
        path,
        state,
        reducers=RULES,
        lock=nullcontext(True),
        condition={"operator": "gt", "path": "delta.ng", "right": 0},
    )
    assert final["totals"] == {"total": 160, "ng": 3}


def test_reducer_time_is_in_batch_budget(tmp_path, monkeypatch):
    """模拟慢归约，在完整记录后停止并保留可继续的游标。"""
    from types import SimpleNamespace
    from backend.nodes.core_nodes.support import file_summary as summary
    from backend.service.application.runtime.io import jsonl

    path, state = tmp_path / "r.jsonl", tmp_path / "state.json"
    for index in range(3):
        append_record(path, {"delta": {"total": 24, "ng": 1}}, operation=str(index))
    clock = [0.0]
    monkeypatch.setattr(jsonl, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    original = summary.reduce_record

    def slow(*args):
        original(*args)
        clock[0] += 2

    monkeypatch.setattr(summary, "reduce_record", slow)
    result = summarize(
        path, state, reducers=RULES, lock=nullcontext(True), max_seconds=1
    )
    assert result["totals"]["total"] == 24
    assert result["source"]["sequence"] == 1
    assert result["complete"] is False


def test_twenty_second_batch_budget_resumes_without_recount(tmp_path, monkeypatch):
    """20 秒预算包含归约耗时；跨批次接续且重复读取不重复累计。"""
    from types import SimpleNamespace
    from backend.nodes.core_nodes.support import file_summary as summary
    from backend.service.application.runtime.io import jsonl

    path, state = tmp_path / "r.jsonl", tmp_path / "state.json"
    for index in range(3):
        append_record(path, {"delta": {"total": 24, "ng": 1}}, operation=str(index))
    clock = [0.0]
    monkeypatch.setattr(jsonl, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    original = summary.reduce_record

    def slow(*args):
        original(*args)
        clock[0] += 10

    monkeypatch.setattr(summary, "reduce_record", slow)
    options = dict(
        reducers=RULES,
        max_records=1_000_000,
        max_bytes=128 * 1024 * 1024,
        max_seconds=20,
    )
    first = summarize(path, state, lock=nullcontext(True), **options)
    assert first["totals"] == {"total": 48, "ng": 2}
    assert first["complete"] is False
    final = summarize(path, state, lock=nullcontext(True), **options)
    assert final["totals"] == {"total": 72, "ng": 3}
    assert final["complete"] is True
    assert summarize(path, state, lock=nullcontext(True), **options) == final


def test_checkpoint_compare_and_swap_conflict(tmp_path):
    """另一个读取调用先提交时，不覆盖其检查点。"""
    from contextlib import contextmanager

    path, state = tmp_path / "r.jsonl", tmp_path / "state.json"
    append_record(path, {"delta": {"total": 24, "ng": 1}}, operation="one")

    @contextmanager
    def concurrent_commit():
        state.write_bytes(b"another checkpoint")
        yield True

    with pytest.raises(InvalidRequestError, match="另一调用"):
        summarize(path, state, reducers=RULES, lock=concurrent_commit())
    assert state.read_bytes() == b"another checkpoint"


@pytest.mark.parametrize("cleanup", ["log", "all", "empty", "commit", "checkpoint"])
def test_cleanup_resets_or_rebuilds_count_without_double_counting(tmp_path, cleanup):
    """删日志归零，删派生状态重建，旧新记录均以条数统计盘数。"""
    from backend.service.application.runtime.io.jsonl import sidecars
    from backend.service.application.runtime.io.path_write_coordinator import (
        PathWriteCoordinator,
    )

    path, state = tmp_path / "r.jsonl", tmp_path / "state.json"
    rules = [{"operation": "count", "output_key": "tray_total"}]

    def run():
        return summarize(
            path,
            state,
            reducers=rules,
            lock=nullcontext(True),
            allow_missing=True,
            repair_lock=lambda: PathWriteCoordinator().try_acquire([path]),
        )

    append_record(path, {"tray_total": 1}, operation="one")
    assert run()["totals"]["tray_total"] == 1
    if cleanup in {"log", "all"}:
        path.unlink()
    if cleanup == "empty":
        path.write_bytes(b"")
    if cleanup in {"all", "commit"}:
        sidecars(path)[0].unlink()
    if cleanup in {"all", "checkpoint"}:
        state.unlink()
    expected = 0 if cleanup in {"log", "all", "empty"} else 1
    assert run()["totals"]["tray_total"] == expected
    append_record(path, {"material_total": 24}, operation="two")
    assert run()["totals"]["tray_total"] == expected + 1
    assert run()["totals"]["tray_total"] == expected + 1


def test_log_deleted_between_summary_reads(tmp_path, monkeypatch):
    """外部清理发生在两次读取间时返回空结果，不发布旧统计。"""
    from backend.nodes.core_nodes.support import file_summary as summary

    path, state = tmp_path / "r.jsonl", tmp_path / "state.json"
    append_record(path, {"delta": {"total": 24, "ng": 0}}, operation="one")
    original = summary.read_records
    calls = 0

    def read_then_delete(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            path.unlink()
        return result

    monkeypatch.setattr(summary, "read_records", read_then_delete)
    result = summarize(
        path, state, reducers=RULES, lock=nullcontext(True), allow_missing=True
    )
    assert result["status"] == "empty"
    assert result["totals"] == {"total": 0, "ng": 0}
    assert not state.exists()
