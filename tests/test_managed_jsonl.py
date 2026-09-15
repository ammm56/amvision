"""提交边界、恢复与并发读取的文件协议测试。"""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.io import jsonl
from backend.service.application.runtime.io.path_write_coordinator import (
    PathWriteCoordinator,
)


def append(path, value):
    """独立调用独立记录。"""
    return jsonl.append_record(path, value, operation=uuid4().hex)


@pytest.mark.parametrize(
    "payload", [b'{"n":NaN}\n', b'{"n":Infinity}\n', b'{"n":1e400}\n']
)
def test_snapshot_rejects_nonfinite_numbers(tmp_path, payload):
    """非有限字面量和浮点解析溢出都不能进入显示链路。"""
    path = tmp_path / "external.jsonl"
    path.write_bytes(payload)
    with pytest.raises(InvalidRequestError, match="损坏"):
        jsonl.read_records(path, source_mode="snapshot")


def test_committed_intent_does_not_hide_unknown_tail(tmp_path, monkeypatch):
    """已提交但未清理的意图不能掩盖后来出现的未知尾部。"""
    path = tmp_path / "r.jsonl"
    monkeypatch.setattr(jsonl, "_clear_intent", lambda path: None)
    append(path, {"total": 24})
    with path.open("ab") as stream:
        stream.write(b'{"unexpected":true}\n')
    before = path.read_bytes()
    with pytest.raises(InvalidRequestError, match="冲突"):
        append(path, {"total": 80})
    assert path.read_bytes() == before


def test_incremental_reads_and_new_calls(tmp_path):
    """相同记录追加两次，重复读取不会再产生记录。"""
    path = tmp_path / "records.jsonl"
    append(path, {"total": 24})
    first = jsonl.read_records(path)
    append(path, {"total": 24})
    second = jsonl.read_records(path, cursor=first["next_cursor"])
    assert first["records"] == second["records"] == [{"total": 24}]
    assert jsonl.read_records(path, cursor=second["next_cursor"])["records"] == []


@pytest.mark.parametrize("partial", [False, True])
def test_recovery_after_process_interruption(tmp_path, partial):
    """完整未提交尾部恢复一次，半条尾部恢复到旧提交边界。"""
    path = tmp_path / "records.jsonl"
    original = append(path, {"total": 24})
    payload = jsonl.encode({"total": 80}) + b"\n"
    intent = jsonl.Intent(
        generation=original["generation"],
        operation="interrupted",
        offset=original["committed_offset"],
        sequence=2,
        length=len(payload),
        digest=hashlib.sha256(payload).hexdigest(),
    )
    jsonl.atomic_write_bytes(jsonl.sidecars(path)[1], jsonl.encode(intent.model_dump()))
    with path.open("ab") as stream:
        stream.write(payload[:3] if partial else payload)
    assert jsonl.read_records(path)["records"] == [{"total": 24}]
    jsonl.append_record(path, {"total": 80}, operation="interrupted")
    assert jsonl.read_records(path)["records"] == [{"total": 24}, {"total": 80}]


def test_commit_failure_does_not_publish_or_duplicate(tmp_path, monkeypatch):
    """日志已 fsync、发布失败的恢复仍只计一次。"""
    path = tmp_path / "records.jsonl"
    append(path, {"n": 1})
    original = jsonl._publish

    def fail_publish(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(jsonl, "_publish", fail_publish)
    with pytest.raises(OSError):
        jsonl.append_record(path, {"n": 2}, operation="two")
    assert jsonl.read_records(path)["records"] == [{"n": 1}]
    monkeypatch.setattr(jsonl, "_publish", original)
    jsonl.append_record(path, {"n": 2}, operation="two")
    assert jsonl.read_records(path)["records"] == [{"n": 1}, {"n": 2}]


def test_fixed_read_boundary_and_budgets(tmp_path):
    """持续写入时当前读取仍能追到固定边界。"""
    path = tmp_path / "records.jsonl"
    for n in range(3):
        append(path, {"n": n})
    first = jsonl.read_records(path, max_records=1)
    append(path, {"n": 3})
    rest = jsonl.read_records(
        path, cursor=first["next_cursor"], snapshot_end=first["snapshot_end"]
    )
    assert rest["records"] == [{"n": 1}, {"n": 2}]
    assert not rest["has_more"]
    with pytest.raises(InvalidRequestError):
        jsonl.read_records(path, max_bytes=1)


def test_corruption_missing_and_replacement(tmp_path):
    """不能把损坏元数据、替换文件或坏行当成空记录。"""
    path = tmp_path / "records.jsonl"
    assert jsonl.read_records(path, allow_missing=True)["status"] == "missing"
    append(path, {"n": 1})
    replacement = tmp_path / "new"
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    with pytest.raises(InvalidRequestError):
        jsonl.read_records(path)
    jsonl.sidecars(path)[0].unlink()
    with pytest.raises(InvalidRequestError):
        append(path, {"n": 2})


def _try_lock(path, connection):
    """子进程尝试路径锁，不能无限等待。"""
    with PathWriteCoordinator().try_acquire([Path(path)]) as acquired:
        connection.send(acquired)
    connection.close()


def test_cross_process_lock_is_fail_fast(tmp_path):
    """真实跨进程冲突及时拒绝，退出后可重新获取。"""
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    path = tmp_path / "records.jsonl"
    coordinator = PathWriteCoordinator()
    with coordinator.try_acquire([path]) as acquired:
        assert acquired
        process = context.Process(target=_try_lock, args=(str(path), child))
        process.start()
        assert parent.poll(10)
        assert parent.recv() is False
        process.join(10)
        assert process.exitcode == 0
    with coordinator.try_acquire([path]) as acquired:
        assert acquired
    parent.close()
    child.close()
