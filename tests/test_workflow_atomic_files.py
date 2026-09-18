"""Windows 真实句柄冲突、控制文件发布和文件节点诊断回归。"""

import errno
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from backend.service.application.errors import ServiceError
from backend.service.application.runtime.io import atomic_files
from backend.service.application.runtime.io.jsonl import (
    append_record,
    read_records,
    sidecars,
)
from backend.service.infrastructure.filesystem.shared_files import open_shared_read


def _hold_control_files(paths, connection):
    """子进程持有替换前的控制文件，直到主进程完成发布。"""
    from contextlib import ExitStack

    with ExitStack() as stack:
        streams = [stack.enter_context(open_shared_read(Path(p))) for p in paths]
        connection.send("ready")
        assert connection.poll(20)
        assert connection.recv() == "read"
        connection.send([stream.read() for stream in streams])
    connection.close()


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows 文件共享语义")
def test_plain_reader_reproduces_access_denied(tmp_path):
    """普通读取句柄能在本机稳定复现原子替换拒绝访问。"""
    path = tmp_path / "summary.json"
    path.write_bytes(b"old")
    source = tmp_path / "source.json"
    source.write_bytes(b"new")
    with path.open("rb") as stream:
        with pytest.raises(PermissionError) as caught:
            os.replace(source, path)
        assert caught.value.winerror in {5, 32}
        assert stream.read() == b"old"
    assert path.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.tmp"))
    atomic_files.atomic_write_bytes(path, b"new")
    assert path.read_bytes() == b"new"


def test_cross_process_readers_do_not_block_commit_and_summary(tmp_path):
    """持有旧 commit/checkpoint 的读者不阻止生产追加和汇总发布。"""
    from backend.nodes.core_nodes.support.file_summary import summarize
    from backend.service.application.runtime.io.path_write_coordinator import (
        PathWriteCoordinator,
    )

    path, state = tmp_path / "records.jsonl", tmp_path / "summary.json"
    coordinator = PathWriteCoordinator()
    rules = [dict(output_key="total", source_path="total", operation="sum")]

    def run():
        return summarize(
            path, state, reducers=rules, lock=coordinator.try_acquire([state])
        )

    append_record(path, {"total": 24}, operation="first")
    assert run()["totals"] == {"total": 24}
    commit = sidecars(path)[0]
    old = [commit.read_bytes(), state.read_bytes()]
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_hold_control_files, args=([str(commit), str(state)], child)
    )
    process.start()
    child.close()
    try:
        assert parent.poll(20)
        assert parent.recv() == "ready"
        with coordinator.try_acquire([path]) as acquired:
            assert acquired
            append_record(path, {"total": 80}, operation="second")
        assert run()["totals"] == {"total": 104}
        parent.send("read")
        assert parent.poll(20)
        assert parent.recv() == old
        assert json.loads(commit.read_bytes())["sequence"] == 2
        assert read_records(path)["records"] == [{"total": 24}, {"total": 80}]
        process.join(20)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()
        coordinator.close()


def test_shared_reader_preserves_missing_error(tmp_path):
    """缺失错误保留具体路径，而不是读取为空或掩盖系统错误。"""
    path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError) as caught:
        open_shared_read(path)
    assert caught.value.filename == str(path)


def test_native_paths_do_not_truncate_at_nul(tmp_path):
    """Win32 字符串参数不能把非法路径截成另一个有效文件名。"""
    from backend.service.infrastructure.filesystem.shared_files import replace_shared_file

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    with pytest.raises(ValueError):
        replace_shared_file(source, Path(str(target) + "\0unexpected"))
    with pytest.raises(ValueError):
        open_shared_read(Path(str(target) + "\0unexpected"))
    assert target.read_bytes() == b"old"
    assert source.read_bytes() == b"new"


@pytest.mark.skipif(os.name != "nt", reason="验证 Win32 错误码传递")
def test_shared_reader_does_not_report_access_denied_as_missing(tmp_path, monkeypatch):
    """CreateFile 拒绝访问不能误报为不存在。"""
    import ctypes
    from ctypes import wintypes
    from backend.service.infrastructure.filesystem import shared_files

    def denied(*args):
        ctypes.set_last_error(5)
        return wintypes.HANDLE(-1).value

    monkeypatch.setattr(shared_files, "_create_file", denied)
    with pytest.raises(PermissionError) as caught:
        open_shared_read(tmp_path / "denied.json")
    assert caught.value.winerror == 5


@pytest.mark.skipif(os.name != "nt", reason="验证原生替换失败不会降级为删除重写")
def test_unsupported_native_replace_keeps_old_file(tmp_path, monkeypatch):
    """文件系统不支持时直接失败，不删除旧文件或退回不安全替换。"""
    import ctypes
    from backend.service.infrastructure.filesystem import shared_files

    path = tmp_path / "state.json"
    path.write_bytes(b"old")

    def unsupported(*args):
        ctypes.set_last_error(50)
        return 0

    monkeypatch.setattr(shared_files, "_set_file_information", unsupported)
    with pytest.raises(OSError) as caught:
        atomic_files.atomic_write_bytes(path, b"new")
    assert caught.value.winerror == 50
    assert path.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.tmp"))


def test_unicode_long_path_and_held_reader(tmp_path):
    """中文、非 BMP 字符和长路径均准确发布，读者持有原内容。"""
    directory = tmp_path / ("a" * 90) / ("b" * 90) / ("c" * 90)
    path = directory / "治具汇总-📷.json"
    atomic_files.atomic_write_bytes(path, b"old")
    with open_shared_read(path) as stream:
        atomic_files.atomic_write_bytes(path, b"new")
        assert stream.read() == b"old"
    with open_shared_read(path) as stream:
        assert stream.read() == b"new"


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows 只读属性和句柄释放")
def test_readonly_target_is_not_overwritten_and_handles_are_closed(tmp_path):
    """拒绝只读覆盖；成功与失败后的 native handle 都须关闭。"""
    import ctypes
    import stat
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process = kernel32.GetCurrentProcess
    process.restype = wintypes.HANDLE
    count = kernel32.GetProcessHandleCount
    count.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    count.restype = wintypes.BOOL

    def handles():
        """读取测试进程的 Windows handle 总数。"""
        value = wintypes.DWORD()
        assert count(process(), ctypes.byref(value))
        return value.value

    path = tmp_path / "readonly.json"
    atomic_files.atomic_write_bytes(path, b"old")
    try:
        path.chmod(stat.S_IREAD)
        for _ in range(20):
            with pytest.raises(PermissionError):
                atomic_files.atomic_write_bytes(path, b"new")
        # WinError 首次格式化会加载 Windows 消息资源，先预热再检查稳定值。
        before = handles()
        for _ in range(20):
            with pytest.raises(PermissionError):
                atomic_files.atomic_write_bytes(path, b"new")
        assert handles() <= before + 2
        assert path.read_bytes() == b"old"
    finally:
        path.chmod(stat.S_IWRITE)
    for _ in range(10):
        with open_shared_read(path) as stream:
            atomic_files.atomic_write_bytes(path, b"new")
            stream.read()
    before = handles()
    for _ in range(100):
        with open_shared_read(path) as stream:
            atomic_files.atomic_write_bytes(path, b"new")
            assert stream.read() in {b"old", b"new"}
    assert handles() <= before + 2


def test_flush_failure_does_not_publish(tmp_path, monkeypatch):
    """持久化失败时旧文件保持原样，不能把未落盘临时文件发布出去。"""
    path = tmp_path / "state.json"
    path.write_bytes(b"old")

    def failed_flush(*args):
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(atomic_files.os, "fsync", failed_flush)
    with pytest.raises(OSError) as caught:
        atomic_files.atomic_write_bytes(path, b"new")
    assert caught.value.file_io_stage == "flush_temporary"
    assert path.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.tmp"))


def test_commit_verification_keeps_original_publish_error(tmp_path, monkeypatch):
    """发布及读回均失败，诊断仍以最初的发布错误为主。"""
    from backend.service.application.runtime.io import jsonl

    path = tmp_path / "records.jsonl"
    append_record(path, {"n": 1}, operation="first")
    commit = jsonl._commit(path)
    original = PermissionError(errno.EACCES, "publish denied")

    def failed_publish(*args):
        raise original

    def failed_verify(*args):
        raise OSError(errno.EIO, "readback failed")

    monkeypatch.setattr(jsonl, "atomic_write_bytes", failed_publish)
    monkeypatch.setattr(jsonl, "read_small", failed_verify)
    with pytest.raises(PermissionError) as caught:
        jsonl._publish(path, commit)
    assert caught.value is original
    assert "readback failed" in caught.value.file_io_verification_error


def test_cleanup_failure_keeps_original_write_error(tmp_path, monkeypatch):
    """临时文件清理也失败时，原始磁盘错误和操作阶段不能丢失。"""
    path = tmp_path / "summary.json"
    path.write_bytes(b"old")
    original = OSError(errno.ENOSPC, "disk full")

    def no_space(*args):
        raise original

    def cannot_cleanup(*args, **kwargs):
        raise PermissionError(errno.EACCES, "cleanup denied")

    with monkeypatch.context() as patch:
        patch.setattr(atomic_files, "replace_shared_file", no_space)
        patch.setattr(Path, "unlink", cannot_cleanup)
        with pytest.raises(OSError) as caught:
            atomic_files.atomic_write_bytes(path, b"new")
    assert caught.value is original
    assert caught.value.file_io_stage == "replace"
    assert caught.value.file_io_path == str(path)
    assert "cleanup denied" in caught.value.file_io_cleanup_error
    assert path.read_bytes() == b"old"
    for temporary in tmp_path.glob("*.tmp"):
        temporary.unlink()


def test_no_overwrite_cannot_replace_racing_creator(tmp_path, monkeypatch):
    """目标在准备临时文件之后出现，也不得被 overwrite=False 覆盖。"""
    path = tmp_path / "summary.json"
    publish = atomic_files.publish_path_without_overwrite

    def competing_create(source, target):
        target.write_bytes(b"other writer")
        return publish(source, target)

    monkeypatch.setattr(
        atomic_files, "publish_path_without_overwrite", competing_create
    )
    with pytest.raises(FileExistsError):
        atomic_files.atomic_write_bytes(path, b"new", overwrite=False)
    assert path.read_bytes() == b"other writer"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows 外部不共享句柄")
def test_append_node_reports_unconfirmed_commit_and_can_recover(tmp_path):
    """外部程序阻挡 commit 时给出路径/阶段；相同物理调用恢复不重复写。"""
    from backend.nodes.core_nodes.io.output.storage.jsonl_append_local import (
        CORE_NODE_SPEC,
    )
    from backend.service.application.workflows.execution.contracts import (
        WorkflowNodeExecutionRequest,
    )

    path = tmp_path / "records.jsonl"
    append_record(path, {"n": 1}, operation="first")
    request = WorkflowNodeExecutionRequest(
        node_id="append",
        node_definition=CORE_NODE_SPEC.node_definition,
        parameters={"save_location": str(path)},
        input_values={"value": {"value": {"n": 2}}},
        execution_metadata={"workflow_run_id": "same-run"},
        node_invocation_id="same-call",
    )
    commit = sidecars(path)[0]
    with commit.open("rb"):
        with pytest.raises(ServiceError) as caught:
            CORE_NODE_SPEC.handler(request)
    details = caught.value.details
    assert details["error_code"] in {"file_access_denied", "file_busy"}
    assert details["path"] == str(commit)
    assert details["stage"] == "replace"
    assert details["winerror"] in {5, 32}
    assert details["write_state"] == "unconfirmed"
    assert read_records(path)["records"] == [{"n": 1}]
    CORE_NODE_SPEC.handler(request)
    assert read_records(path)["records"] == [{"n": 1}, {"n": 2}]


@pytest.mark.parametrize(
    "number,code",
    [
        (errno.ENOSPC, "disk_full"),
        (errno.EROFS, "filesystem_read_only"),
        (errno.EIO, "file_io_failed"),
    ],
)
def test_file_io_error_diagnostics(tmp_path, number, code):
    """磁盘满、只读和普通 IO 错误分类明确，不自动等待或重跑。"""
    from backend.service.application.runtime.io.file_errors import file_io_errors

    path = tmp_path / "summary.json"
    with pytest.raises(ServiceError) as caught:
        with file_io_errors(path, operation="file_summary"):
            raise OSError(number, "injected", str(path))
    assert caught.value.code == code
    assert caught.value.details["errno"] == number
    assert caught.value.details["path"] == str(path)
