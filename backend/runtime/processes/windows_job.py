"""Windows Job Object 适配器；不承担业务启动或恢复编排。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess
import sys
from uuid import uuid4


class WindowsJob:
    """使用 kill-on-close Job Object 约束 bootstrap 与完整子进程树。"""

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        pass

    _EXTENDED_LIMIT_INFORMATION._fields_ = [
        ("BasicLimitInformation", _BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

    def __init__(self, *, name: str | None = None, open_existing: bool = False) -> None:
        """创建并配置 Job Object。"""

        if sys.platform != "win32":
            raise RuntimeError("WindowsJob 只能在 Windows 使用")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
        self.name = name or ("Local\\amvision-process-" + uuid4().hex)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenJobObjectW.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.OpenJobObjectW.restype = wintypes.HANDLE
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = (
            kernel32.OpenJobObjectW(0x0004 | 0x0008, False, self.name)
            if open_existing
            else kernel32.CreateJobObjectW(None, self.name)
        )
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle
        if open_existing:
            return
        if ctypes.get_last_error() == 183:
            self.close()
            raise FileExistsError(self.name)
        information = self._EXTENDED_LIMIT_INFORMATION()
        information.BasicLimitInformation.LimitFlags = (
            self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not kernel32.SetInformationJobObject(
            handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign_handle(self, handle: int) -> None:
        """绑定尚未放行的进程句柄；适用于 Popen 和 spawn。"""
        if not self._kernel32.AssignProcessToJobObject(
            self._handle, wintypes.HANDLE(handle)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        """把尚未获准启动真实目标的 bootstrap 加入 Job Object。"""

        self.assign_handle(int(process._handle))  # type: ignore[attr-defined]

    def members(self) -> tuple[int, ...]:
        """查询内核维护的成员列表；容量变化时重试，不按父子快照推断。"""
        capacity = 64
        while capacity <= 1_048_576:

            class ProcessIds(ctypes.Structure):
                _fields_ = [
                    ("assigned", wintypes.DWORD),
                    ("count", wintypes.DWORD),
                    ("ids", ctypes.c_size_t * capacity),
                ]

            result = ProcessIds()
            if self._kernel32.QueryInformationJobObject(
                self._handle, 3, ctypes.byref(result), ctypes.sizeof(result), None
            ):
                return tuple(result.ids[: result.count])
            error = ctypes.get_last_error()
            if error != 234:
                raise ctypes.WinError(error)
            capacity = max(capacity * 2, result.assigned)
        raise RuntimeError("进程组成员数量超出查询上限")

    def terminate(self, exit_code: int = 1) -> None:
        """终止 Job Object 中的全部进程。"""

        if self._handle:
            if not self._kernel32.TerminateJobObject(self._handle, exit_code):
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        """关闭 Job；kill-on-close 会清理仍存活的成员。"""

        handle = getattr(self, "_handle", None)
        if handle:
            if not self._kernel32.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = None
