"""Windows 非等待 byte-range 锁，保留原生错误码。"""

import os

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
