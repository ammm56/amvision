"""owner 锁冲突与真实文件错误的分类回归。"""

import errno
import os

import pytest

from backend.service.infrastructure.ipc import mmap_primitives


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
