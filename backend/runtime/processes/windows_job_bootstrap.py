"""Windows Job Object 放行后的目标进程 bootstrap。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import signal
import subprocess
import sys
from pathlib import Path
from typing import Sequence

_START_TOKEN = b"\x01"


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

    def __init__(self) -> None:
        """创建并配置 Job Object。"""

        if sys.platform != "win32":
            raise RuntimeError("WindowsJob 只能在 Windows 使用")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
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

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle
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

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        """把尚未获准启动真实目标的 bootstrap 加入 Job Object。"""

        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self, exit_code: int = 1) -> None:
        """终止 Job Object 中的全部进程。"""

        if self._handle:
            self._kernel32.TerminateJobObject(self._handle, exit_code)

    def close(self) -> None:
        """关闭 Job；kill-on-close 会清理仍存活的成员。"""

        handle = getattr(self, "_handle", None)
        if handle:
            self._kernel32.CloseHandle(handle)
            self._handle = None


def release_bootstrap(process: subprocess.Popen[bytes]) -> None:
    """在 Job 绑定成功后仅放行一次真实目标进程。"""

    if process.stdin is None:
        raise RuntimeError("Windows bootstrap 缺少控制 pipe")
    process.stdin.write(_START_TOKEN)
    process.stdin.flush()
    process.stdin.close()


def build_bootstrap_command(command: Sequence[str]) -> list[str]:
    """构造等待父进程放行的 bootstrap 命令。"""

    normalized = [str(part) for part in command]
    if not normalized:
        raise ValueError("command 不能为空")
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--",
        *normalized,
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """等待单字节放行信号，再启动继承当前 Job 的真实目标进程。"""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] != "--" or len(arguments) == 1:
        return 2
    command = arguments[1:]
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    if sys.stdin.buffer.read(1) != _START_TOKEN:
        return 125
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
    return int(process.wait())


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WindowsJob", "build_bootstrap_command", "main", "release_bootstrap"]
