"""按打开句柄归属的非等待 byte-range 锁，保留原生错误码。"""

import os
import sys

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class _Overlapped(ctypes.Structure):
        """64-bit OVERLAPPED；项目只支持 64-bit 进程。"""

        _fields_ = [
            ("internal", ctypes.c_size_t),
            ("internal_high", ctypes.c_size_t),
            ("offset", wintypes.DWORD),
            ("offset_high", wintypes.DWORD),
            ("event", wintypes.HANDLE),
        ]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _lock = _kernel.LockFileEx
    _lock.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_Overlapped),
    ]
    _lock.restype = wintypes.BOOL
    _unlock = _kernel.UnlockFileEx
    _unlock.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_Overlapped),
    ]
    _unlock.restype = wintypes.BOOL

elif sys.platform == "linux":
    import ctypes
    import fcntl

    class _Flock(ctypes.Structure):
        """Linux 64-bit struct flock；OFD l_pid 固定为零。"""

        _fields_ = [
            ("type", ctypes.c_short),
            ("whence", ctypes.c_short),
            ("start", ctypes.c_int64),
            ("length", ctypes.c_int64),
            ("pid", ctypes.c_int),
        ]


def change_windows_lock(file_object, *, offset: int, unlock: bool = False) -> None:
    """立即获取或释放一个字节的排他锁，异常包含准确 winerror。"""
    operation = _Overlapped(offset=offset & 0xFFFFFFFF, offset_high=offset >> 32)
    handle = msvcrt.get_osfhandle(file_object.fileno())
    result = (
        _unlock(handle, 0, 1, 0, ctypes.byref(operation))
        if unlock
        else _lock(handle, 3, 0, 1, 0, ctypes.byref(operation))
    )
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())


def change_posix_lock(file_object, *, offset: int, unlock: bool = False) -> None:
    """Linux OFD 锁随本句柄释放，不能降级为进程级 lockf。"""
    if sys.platform != "linux":
        raise RuntimeError("当前路径写协调只验收 Windows 和 Linux 的句柄归属锁")
    if (
        ctypes.sizeof(ctypes.c_void_p) != 8
        or ctypes.sizeof(_Flock) != 32
        or _Flock.start.offset != 8
    ):
        raise RuntimeError("不支持当前进程的 Linux flock ABI")
    operation = _Flock(
        type=fcntl.F_UNLCK if unlock else fcntl.F_WRLCK,
        whence=os.SEEK_SET,
        start=offset,
        length=1,
        pid=0,
    )
    fcntl.fcntl(file_object.fileno(), fcntl.F_OFD_SETLK, bytes(operation))
