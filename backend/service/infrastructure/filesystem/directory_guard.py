"""目录生命周期保护；保存和清理共享，禁止跟随重定向目录。"""

from contextlib import ExitStack, contextmanager
import errno
import os
from pathlib import Path
import stat
from time import monotonic, sleep

from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path


class UnsafeDirectoryError(OSError):
    """目录路径包含链接、reparse point 或不稳定身份。"""


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _create = _kernel.CreateFileW
    _create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _create.restype = wintypes.HANDLE
    _close = _kernel.CloseHandle
    _close.argtypes = [wintypes.HANDLE]
    _close.restype = wintypes.BOOL

    class _FileInfo(ctypes.Structure):
        """BY_HANDLE_FILE_INFORMATION，用句柄确认目录类型。"""

        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME),
            ("modified", wintypes.FILETIME),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        ]

    _info = _kernel.GetFileInformationByHandle
    _info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
    _info.restype = wintypes.BOOL
    _set_info = _kernel.SetFileInformationByHandle
    _set_info.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _set_info.restype = wintypes.BOOL


@contextmanager
def protect_directory(
    path: Path, *, create: bool = False, protected_root: Path | None = None
):
    """从根到叶保护祖先链；Windows 共享读写但不共享删除。

    句柄随调用释放，不缓存路径。POSIX 使用共享 flock 与清理协作。
    create 只用于写入准备；目录消失最多三次立即恢复，原生共享冲突最多 100 ms。
    """
    absolute = Path(os.path.abspath(path))
    directories = (*reversed(absolute.parents), absolute)
    if protected_root is not None:
        # 调用方必须在整个操作中持有根目录及祖先的保护，避免逐文件重复打开。
        root = Path(os.path.abspath(protected_root))
        absolute.relative_to(root)
        directories = tuple(
            directory
            for directory in directories
            if directory != root and directory.is_relative_to(root)
        )
    with ExitStack() as stack:
        collision_deadline = None
        for directory in directories:
            missing_attempts = 0
            while True:
                try:
                    if create and missing_attempts:
                        directory.mkdir(exist_ok=True)
                    stack.enter_context(protect_child_directory(directory))
                    break
                except OSError as error:
                    if create and isinstance(error, FileNotFoundError):
                        missing_attempts += 1
                        if missing_attempts < 3:
                            continue
                    elif create and getattr(error, "winerror", None) in {32, 33, 303}:
                        # 竞争者可能在另一个线程/进程；忙循环会阻止其关闭删除句柄。
                        # 仅目录准备有界让出调度，正常保存及文件写入没有等待。
                        now = monotonic()
                        if collision_deadline is None:
                            collision_deadline = now + 0.1
                        if now < collision_deadline:
                            sleep(min(0.001, collision_deadline - now))
                            continue
                    error.file_io_stage = "protect_directory"
                    error.file_io_path = str(directory)
                    raise
        yield absolute


@contextmanager
def protect_child_directory(path: Path):
    """保护单一目录；调用方已经保护父路径，不解析链接。"""
    if os.name == "nt":
        handle = _create(
            str(to_filesystem_path(path)), 1, 3, None, 3, 0x02000000 | 0x00200000, None
        )
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = _FileInfo()
            if not _info(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400 or not info.attributes & 0x10:
                raise UnsafeDirectoryError(errno.ELOOP, "不允许重定向目录", str(path))
            yield
        finally:
            _close(handle)
    else:
        import fcntl

        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            observed = os.fstat(descriptor)
            current = path.stat(follow_symlinks=False)
            if (observed.st_dev, observed.st_ino) != (current.st_dev, current.st_ino):
                raise UnsafeDirectoryError(errno.ELOOP, "目录身份已变化", str(path))
            yield
        finally:
            os.close(descriptor)


def delete_windows_file_if_unchanged(path: Path, matches) -> str:
    """Windows 按同一文件句柄重检并删除；占用时立即返回，不等待写入者。"""
    handle = _create(
        str(to_filesystem_path(path)), 0x10080, 1, None, 3, 0x00200000, None
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.WinError(ctypes.get_last_error())
        if error.winerror in {2, 3}:
            return "missing"
        if error.winerror in {32, 33}:
            return "locked"
        raise error
    try:
        info = _FileInfo()
        if not _info(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & (0x400 | 0x10):
            return "changed"
        # 此句柄禁止新写入/替换，stat 与 disposition 始终针对同一对象。
        if not matches(to_filesystem_path(path).stat(follow_symlinks=False)):
            return "changed"
        disposition = wintypes.BOOL(True)
        if not _set_info(
            handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return "deleted"
    finally:
        _close(handle)


def remove_empty_directory(path: Path) -> bool:
    """非等待删除空目录；正在保存、非空、消失均正常跳过。"""
    if os.name != "nt":
        raise NotImplementedError(
            "空目录删除需要经过验证的句柄保护；当前仅支持 Windows"
        )
    try:
        with protect_directory(path.parent):
            observed = path.stat(follow_symlinks=False)
            if (
                not stat.S_ISDIR(observed.st_mode)
                or getattr(observed, "st_file_attributes", 0) & 0x400
            ):
                return False
            handle = _create(
                str(to_filesystem_path(path)),
                0x10001,
                3,
                None,
                3,
                0x02000000 | 0x00200000,
                None,
            )
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                info = _FileInfo()
                if not _info(handle, ctypes.byref(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if info.attributes & 0x400 or not info.attributes & 0x10:
                    return False
                disposition = wintypes.BOOL(True)
                if not _set_info(
                    handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                _close(handle)
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        if error.errno in {errno.ENOTEMPTY, errno.EEXIST, errno.EAGAIN} or getattr(
            error, "winerror", None
        ) in {32, 33, 145}:
            return False
        raise
