"""owner 锁冲突与真实文件错误的分类回归。"""

import errno
import os
import subprocess
import sys
from contextlib import ExitStack
from time import monotonic_ns

import pytest

from backend.service.infrastructure.ipc import mmap_primitives


def _paused_process_probe(path, entered, resume, results):
    """子进程在打开只读句柄后等待，按受控顺序进行真实内核查询。"""
    original = mmap_primitives._owner_lock_held_on_handle

    def observe(handle):
        entered.set()
        if not resume.wait(15):
            raise TimeoutError("probe was not resumed")
        return original(handle)

    mmap_primitives._owner_lock_held_on_handle = observe
    try:
        results.put(mmap_primitives.is_mmap_owner_lock_held(path))
    finally:
        mmap_primitives._owner_lock_held_on_handle = original


@pytest.mark.parametrize("size", [0, 1])
def test_independent_process_probes_do_not_take_publisher_ownership(tmp_path, size):
    """两个真实进程都处于探测窗口时，新 publisher 仍可取得唯一所有权。"""
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    path = tmp_path / "owner.lock"
    path.write_bytes(b"x" * size)
    resume, results = context.Event(), context.Queue()
    entered = [context.Event(), context.Event()]
    children = [context.Process(target=_paused_process_probe, args=(path, event, resume, results)) for event in entered]
    owner = None
    try:
        for child in children:
            child.start()
        assert all(event.wait(10) for event in entered)
        assert not mmap_primitives.is_mmap_owner_lock_held(path)
        owner = mmap_primitives.acquire_mmap_owner_lock(path)
        with pytest.raises(mmap_primitives.MmapOwnerLockBusyError):
            mmap_primitives.acquire_mmap_owner_lock(path)
        resume.set()
        assert results.get(timeout=10) is True
        assert results.get(timeout=10) is True
        for child in children:
            child.join(10)
            assert child.exitcode == 0
    finally:
        resume.set()
        if owner is not None:
            owner.release()
        for child in children:
            if child.pid is not None:
                child.join(5)
                if child.is_alive():
                    child.terminate()
                    child.join(5)
                child.close()
        results.close()
        results.join_thread()
    assert not mmap_primitives.is_mmap_owner_lock_held(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows 原生错误分类")
@pytest.mark.parametrize("error", [5, 6, 32, 33])
def test_windows_owner_query_only_lock_violation_means_owned(tmp_path, monkeypatch, error):
    """只有 ERROR_LOCK_VIOLATION 是 owner，权限和句柄错误必须原样传播。"""
    import ctypes

    path = tmp_path / "owner.lock"
    path.touch()

    def read_file(*args):
        ctypes.set_last_error(error)
        return 0

    monkeypatch.setattr(mmap_primitives, "_windows_owner_read_file", lambda: read_file)
    if error == 33:
        assert mmap_primitives.is_mmap_owner_lock_held(path)
    else:
        with pytest.raises(OSError) as raised:
            mmap_primitives.is_mmap_owner_lock_held(path)
        assert raised.value.winerror == error


@pytest.mark.parametrize("size", [0, 1])
def test_owner_probe_is_read_only_and_observes_real_exclusion(tmp_path, size):
    """探测只观察内核锁；同进程不同 handle 也必须识别真实 owner。"""
    path = tmp_path / "observed.lock"
    path.write_bytes(b"x" * size)
    probe = mmap_primitives.is_mmap_owner_lock_held
    assert probe(path) is False
    owner = mmap_primitives.acquire_mmap_owner_lock(path)
    try:
        for _ in range(10):
            assert probe(path) is True
        with pytest.raises(mmap_primitives.MmapOwnerLockBusyError):
            mmap_primitives.acquire_mmap_owner_lock(path)
    finally:
        owner.release()
    assert probe(path) is False
    assert path.read_bytes() == b"x" * size


def test_owner_probe_does_not_create_missing_files(tmp_path):
    """缺失文件是不可观测，不创建一个新的假 owner 身份。"""
    path = tmp_path / "missing" / "owner.lock"
    with pytest.raises(FileNotFoundError):
        mmap_primitives.is_mmap_owner_lock_held(path)
    assert not path.parent.exists()


def test_paused_owner_probe_does_not_block_publisher(tmp_path, monkeypatch):
    """固定探测持有读取 handle 的窗口，真实 publisher 仍可立即取得独占锁。"""
    from threading import Event, Thread

    path = tmp_path / "owner.lock"
    path.touch()
    entered, resume = Event(), Event()
    original = mmap_primitives._owner_lock_held_on_handle
    results = []

    def paused(handle):
        entered.set()
        assert resume.wait(5)
        return original(handle)

    monkeypatch.setattr(mmap_primitives, "_owner_lock_held_on_handle", paused)
    thread = Thread(target=lambda: results.append(mmap_primitives.is_mmap_owner_lock_held(path)))
    thread.start()
    owner = None
    try:
        assert entered.wait(5)
        owner = mmap_primitives.acquire_mmap_owner_lock(path)
        resume.set()
        thread.join(5)
        assert not thread.is_alive()
        assert results == [True]
    finally:
        resume.set()
        thread.join(5)
        if owner is not None:
            owner.release()


def test_owner_probe_preserves_io_failure(tmp_path, monkeypatch):
    """真实 I/O 故障既不是锁占用，也不是已退出。"""
    path = tmp_path / "owner.lock"
    path.touch()
    handles = []

    def fail(handle):
        handles.append(handle)
        raise PermissionError(errno.EACCES, "injected permission failure")

    monkeypatch.setattr(mmap_primitives, "_owner_lock_held_on_handle", fail)
    with pytest.raises(PermissionError):
        mmap_primitives.is_mmap_owner_lock_held(path)
    assert handles[0].closed


@pytest.mark.skipif(os.name == "nt", reason="Windows 活动文件 handle 禁止删除共享")
def test_owner_probe_rejects_path_replaced_during_query(tmp_path, monkeypatch):
    """查询期间被换成另一个 inode 时不能返回旧文件的锁状态。"""
    path = tmp_path / "owner.lock"
    path.touch()
    identity = path.stat()

    def replace_path(_handle):
        path.rename(path.with_suffix(".old"))
        path.touch()
        return False

    monkeypatch.setattr(mmap_primitives, "_owner_lock_held_on_handle", replace_path)
    with pytest.raises(mmap_primitives.MmapGuardFileError, match="身份"):
        mmap_primitives.is_mmap_owner_lock_held(path, expected_identity=(identity.st_dev, identity.st_ino))


def test_guard_pool_reuses_handles_without_weakening_exclusion(tmp_path, monkeypatch):
    """复用不等于共享活动句柄；嵌套同 range 仍须发生真实锁冲突。"""
    path = tmp_path / "pooled.guard"
    path.write_bytes(b"xx")
    opened = []
    original = mmap_primitives._open_existing_guard_range

    def record(*args, **kwargs):
        handle = original(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(mmap_primitives, "_open_existing_guard_range", record)
    with path.open("r+b", buffering=0) as identity:
        pool = mmap_primitives.MmapGuardPool(path, identity)

        def guard(offset=0):
            return mmap_primitives.acquire_mmap_guard(
                guard_path=path, guard_pool=pool, offset=offset,
                deadline_ns=monotonic_ns(), poll_interval_seconds=.001,
            )

        try:
            for _ in range(20):
                with guard():
                    pass
            assert len(opened) == 1
            with guard():
                with pytest.raises(mmap_primitives.MmapGuardBusyError):
                    with guard():
                        pytest.fail("活动租借必须使用不同 open handle")
                with guard(1):
                    pass
                with pytest.raises(mmap_primitives.MmapGuardBusyError):
                    pool.close()
            with guard():
                pass
        finally:
            pool.close()
        assert all(handle.closed for handle in opened)
        with pytest.raises(mmap_primitives.MmapGuardFileError, match="关闭"):
            with guard():
                pass


def test_guard_pool_retains_fixed_number_of_idle_handles(tmp_path):
    """并行锁不排队，峰值过后最多留八个空闲句柄。"""
    path = tmp_path / "bounded.guard"
    path.write_bytes(bytes(16))
    with path.open("r+b", buffering=0) as identity:
        pool = mmap_primitives.MmapGuardPool(path, identity)
        try:
            with ExitStack() as stack:
                for index in range(16):
                    stack.enter_context(mmap_primitives.acquire_mmap_guard(
                        guard_path=path, guard_pool=pool, offset=index,
                        deadline_ns=monotonic_ns(), poll_interval_seconds=.001,
                    ))
                assert pool._active == 16
            assert pool._active == 0
            assert len(pool._idle) == 8
        finally:
            pool.close()


@pytest.mark.parametrize("operation", ["try_lock_byte_range_file", "unlock_byte_range_file"])
def test_guard_pool_discards_handle_after_lock_io_failure(tmp_path, monkeypatch, operation):
    """失败的 lock/unlock 不得把可能仍锁定或无效的 handle 放回池中。"""
    path = tmp_path / "failed.guard"
    path.write_bytes(b"x")
    seen = []

    def fail(handle, **kwargs):
        seen.append(handle)
        raise OSError(errno.EIO, "injected lock IO failure")

    with path.open("r+b", buffering=0) as identity:
        pool = mmap_primitives.MmapGuardPool(path, identity)
        with monkeypatch.context() as patch:
            patch.setattr(mmap_primitives, operation, fail)
            with pytest.raises(OSError, match="IO failure"):
                with mmap_primitives.acquire_mmap_guard(
                    guard_path=path, guard_pool=pool,
                    deadline_ns=monotonic_ns(), poll_interval_seconds=.001,
                ):
                    pass
        assert seen[0].closed
        assert pool._active == 0 and pool._idle == []
        with mmap_primitives.acquire_mmap_guard(
            guard_path=path, guard_pool=pool,
            deadline_ns=monotonic_ns(), poll_interval_seconds=.001,
        ):
            pass
        pool.close()


def test_guard_pool_rechecks_length_of_cached_handle(tmp_path):
    """首次校验不能掩盖后续 guard 截断。"""
    path = tmp_path / "truncated.guard"
    path.write_bytes(b"xx")
    with path.open("r+b", buffering=0) as identity:
        pool = mmap_primitives.MmapGuardPool(path, identity)
        handle = pool.borrow(guard_path=path, minimum_size=1)
        pool.release(handle)
        identity.truncate(1)
        try:
            with pytest.raises(mmap_primitives.MmapGuardFileError, match="长度"):
                pool.borrow(guard_path=path, minimum_size=1)
            assert handle.closed
            assert pool._active == 0
        finally:
            pool.close()


@pytest.mark.skipif(os.name == "nt", reason="Windows 活动 guard 文件禁止路径替换")
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("replacement", ["unlink", "rename"])
def test_guard_pool_rejects_replaced_file_identity(tmp_path, cached, replacement):
    """首次及缓存租借均不能在路径替换后继续锁住已脱离路径的 inode。"""
    path = tmp_path / "replaced.guard"
    path.write_bytes(b"xx")
    with path.open("r+b", buffering=0) as identity:
        pool = mmap_primitives.MmapGuardPool(path, identity)
        if cached:
            handle = pool.borrow(guard_path=path, minimum_size=1)
            pool.release(handle)
        if replacement == "unlink":
            path.unlink()
        else:
            path.rename(path.with_suffix(".old"))
        path.write_bytes(b"xx")
        try:
            with pytest.raises(mmap_primitives.MmapGuardFileError, match="身份"):
                borrowed = pool.borrow(guard_path=path, minimum_size=1)
                pool.release(borrowed)
            assert pool._active == 0
        finally:
            pool.close()


@pytest.mark.skipif(os.name == "nt", reason="Windows 活动 guard 文件禁止删除")
def test_guard_pool_rejects_missing_path_with_cached_handle(tmp_path):
    """路径消失不能由缓存的存活 inode 掩盖，失败仍正确释放活动计数。"""
    path = tmp_path / "missing.guard"
    path.write_bytes(b"xx")
    with path.open("r+b", buffering=0) as identity:
        pool = mmap_primitives.MmapGuardPool(path, identity)
        handle = pool.borrow(guard_path=path, minimum_size=1)
        pool.release(handle)
        path.unlink()
        try:
            with pytest.raises(mmap_primitives.MmapGuardFileError, match="身份"):
                borrowed = pool.borrow(guard_path=path, minimum_size=1)
                pool.release(borrowed)
            assert handle.closed and pool._active == 0
        finally:
            pool.close()


def test_owner_lock_is_exclusive_even_in_same_process(tmp_path):
    """不同 owner 句柄不能因属于同一进程而同时取得锁。"""
    path = tmp_path / "owner.lock"
    owner = mmap_primitives.acquire_mmap_owner_lock(path)
    try:
        with pytest.raises(mmap_primitives.MmapOwnerLockBusyError):
            mmap_primitives.acquire_mmap_owner_lock(path)
    finally:
        owner.release()
    replacement = mmap_primitives.acquire_mmap_owner_lock(path)
    replacement.release()


def test_closing_other_handle_does_not_release_active_range(tmp_path):
    """同文件其他句柄关闭后，独立进程仍不能进入已有临界区。"""
    path = tmp_path / "guard"
    path.write_bytes(b"xx")
    with mmap_primitives.acquire_mmap_guard(guard_path=path, deadline_ns=monotonic_ns()+10**9,
                                           poll_interval_seconds=.001):
        with path.open("rb"):
            pass
        script = (
            "from backend.service.infrastructure.ipc.mmap_primitives import *; "
            f"h=open({str(path)!r},'r+b',buffering=0); "
            "try_lock_byte_range_file(h)"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=10)
        assert result.returncode != 0
        assert b"BlockingIOError" in result.stderr


def test_independent_handle_ranges_do_not_conflict(tmp_path):
    """修复不能将 byte-range 锁扩大为全文件锁。"""
    path = tmp_path / "guard"
    path.write_bytes(b"xx")
    with mmap_primitives.acquire_mmap_guard(guard_path=path, deadline_ns=monotonic_ns()+10**9,
                                           poll_interval_seconds=.001, offset=0):
        with mmap_primitives.acquire_mmap_guard(guard_path=path, deadline_ns=monotonic_ns()+10**9,
                                               poll_interval_seconds=.001, offset=1):
            pass


def test_owner_lock_preserves_non_contention_io_error(tmp_path, monkeypatch):
    """I/O 故障保留原异常且关闭打开的文件，不能误报另一个 owner。"""
    handles = []

    def fail(handle, **_kwargs):
        handles.append(handle)
        raise OSError(errno.EIO, "injected IO failure")

    monkeypatch.setattr(mmap_primitives, "try_lock_byte_range_file", fail)
    with pytest.raises(OSError) as error:
        mmap_primitives.acquire_mmap_owner_lock(tmp_path / "owner.lock")
    assert error.value.errno == errno.EIO
    assert handles[0].closed


def test_short_guard_preserves_non_contention_io_error(tmp_path, monkeypatch):
    """publication 等待只能消化锁竞争，不能重试真实 I/O 故障。"""
    path = tmp_path / "guard"
    path.write_bytes(b"x")
    handles = []
    def fail(handle, **_):
        handles.append(handle)
        raise OSError(errno.EIO, "disk error")
    monkeypatch.setattr(mmap_primitives, "try_lock_byte_range_file", fail)
    with pytest.raises(OSError, match="disk error"):
        with mmap_primitives.acquire_mmap_guard(guard_path=path, deadline_ns=monotonic_ns()+10**9, poll_interval_seconds=.001):
            pytest.fail("真实 I/O 故障不能被吞掉")
    assert len(handles) == 1 and handles[0].closed


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows msvcrt 异常分类")
def test_windows_byte_lock_preserves_invalid_handle_error(tmp_path, monkeypatch):
    """Windows 无效句柄不是锁争用。"""
    import msvcrt

    def fail(*_args):
        raise OSError(errno.EBADF, "invalid handle")

    monkeypatch.setattr(msvcrt, "locking", fail)
    with (tmp_path / "guard").open("w+b") as handle:
        with pytest.raises(OSError) as error:
            mmap_primitives.try_lock_byte_range_file(handle)
    assert error.value.errno == errno.EBADF
