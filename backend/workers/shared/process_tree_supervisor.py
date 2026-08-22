"""跨平台子进程树监督与有界日志采集。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import contextlib
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Lock, Thread
import time
from typing import BinaryIO, Sequence

from backend.service.application.errors import OperationTimeoutError, ServiceConfigurationError


@dataclass(frozen=True)
class ProcessTreeResult:
    """描述一次受监督进程树执行结果。"""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    stdout_log_path: Path | None = None
    stderr_log_path: Path | None = None

    def to_completed_process(self) -> subprocess.CompletedProcess[str]:
        """转换成兼容现有转换构建器的 ``CompletedProcess``。"""

        return subprocess.CompletedProcess(
            list(self.command),
            self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class _BoundedByteTail:
    """线程安全地保留日志末尾固定字节数。"""

    def __init__(self, capacity_bytes: int) -> None:
        self.capacity_bytes = max(1024, int(capacity_bytes))
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._lock = Lock()

    def append(self, chunk: bytes) -> None:
        """追加日志块并丢弃超出容量的最早内容。"""

        with self._lock:
            self._chunks.append(chunk)
            self._size += len(chunk)
            while self._size > self.capacity_bytes and self._chunks:
                excess = self._size - self.capacity_bytes
                head = self._chunks[0]
                if len(head) <= excess:
                    self._chunks.popleft()
                    self._size -= len(head)
                    continue
                self._chunks[0] = head[excess:]
                self._size -= excess

    def decode(self) -> str:
        """把当前 tail 解码为 UTF-8 文本。"""

        with self._lock:
            payload = b"".join(self._chunks)
        return payload.decode("utf-8", errors="replace")


class _WindowsJob:
    """使用 Windows Job Object 约束完整子孙进程树。"""

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
        """把根进程加入 Job Object。"""

        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self, exit_code: int = 1) -> None:
        """终止 Job Object 中的全部进程。"""

        if self._handle:
            self._kernel32.TerminateJobObject(self._handle, exit_code)

    def close(self) -> None:
        """关闭 Job Object；KILL_ON_JOB_CLOSE 会清理仍存活的成员。"""

        handle = getattr(self, "_handle", None)
        if handle:
            self._kernel32.CloseHandle(handle)
            self._handle = None


class ProcessTreeSupervisor:
    """运行命令、持续排空日志并在 deadline 到达时终止完整进程树。"""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        termination_grace_seconds: float = 5.0,
        tail_capacity_bytes: int = 1024 * 1024,
    ) -> None:
        """初始化监督参数。"""

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self.timeout_seconds = float(timeout_seconds)
        self.termination_grace_seconds = max(0.0, float(termination_grace_seconds))
        self.tail_capacity_bytes = max(1024, int(tail_capacity_bytes))

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        stdout_log_path: Path | None = None,
        stderr_log_path: Path | None = None,
        tee_output: bool = False,
    ) -> ProcessTreeResult:
        """执行命令并返回有界日志 tail。"""

        normalized_command = tuple(str(part) for part in command)
        if not normalized_command:
            raise ValueError("command 不能为空")
        for path in (stdout_log_path, stderr_log_path):
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)

        popen_kwargs: dict[str, object] = {
            "cwd": str(cwd) if cwd is not None else None,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "bufsize": 0,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        started_at = time.monotonic()
        process = subprocess.Popen(list(normalized_command), **popen_kwargs)  # type: ignore[arg-type]
        windows_job: _WindowsJob | None = None
        try:
            if os.name == "nt":
                try:
                    windows_job = _WindowsJob()
                    windows_job.assign(process)
                except Exception as error:
                    self._terminate_process_tree(process, windows_job=None)
                    raise ServiceConfigurationError(
                        "Windows conversion Job Object 初始化失败",
                        details={"process_id": process.pid, "error": str(error)},
                    ) from error

            stdout_tail = _BoundedByteTail(self.tail_capacity_bytes)
            stderr_tail = _BoundedByteTail(self.tail_capacity_bytes)
            stdout_thread = Thread(
                target=_drain_stream,
                args=(process.stdout, stdout_tail),
                kwargs={
                    "log_path": stdout_log_path,
                    "tee_stream": sys.stdout.buffer if tee_output else None,
                },
                daemon=True,
                name=f"process-{process.pid}-stdout",
            )
            stderr_thread = Thread(
                target=_drain_stream,
                args=(process.stderr, stderr_tail),
                kwargs={
                    "log_path": stderr_log_path,
                    "tee_stream": sys.stderr.buffer if tee_output else None,
                },
                daemon=True,
                name=f"process-{process.pid}-stderr",
            )
            stdout_thread.start()
            stderr_thread.start()
            try:
                returncode = process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as error:
                self._terminate_process_tree(process, windows_job=windows_job)
                _join_drain_threads(stdout_thread, stderr_thread)
                raise OperationTimeoutError(
                    "conversion 子进程树执行超时",
                    details={
                        "timeout_seconds": self.timeout_seconds,
                        "process_id": process.pid,
                        "command": list(normalized_command),
                        "stdout_tail": stdout_tail.decode(),
                        "stderr_tail": stderr_tail.decode(),
                        "stdout_log_path": str(stdout_log_path) if stdout_log_path else None,
                        "stderr_log_path": str(stderr_log_path) if stderr_log_path else None,
                    },
                ) from error
            _join_drain_threads(stdout_thread, stderr_thread)
            return ProcessTreeResult(
                command=normalized_command,
                returncode=returncode,
                stdout=stdout_tail.decode(),
                stderr=stderr_tail.decode(),
                duration_seconds=max(0.0, time.monotonic() - started_at),
                stdout_log_path=stdout_log_path,
                stderr_log_path=stderr_log_path,
            )
        finally:
            if process.poll() is None:
                self._terminate_process_tree(process, windows_job=windows_job)
            if windows_job is not None:
                windows_job.close()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    with contextlib.suppress(Exception):
                        stream.close()

    def _terminate_process_tree(
        self,
        process: subprocess.Popen[bytes],
        *,
        windows_job: _WindowsJob | None,
    ) -> None:
        """按平台终止完整进程树。"""

        if process.poll() is not None:
            return
        if os.name == "nt":
            if windows_job is not None:
                windows_job.terminate(exit_code=1)
            else:
                with contextlib.suppress(Exception):
                    process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=max(0.1, self.termination_grace_seconds))
            return

        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=max(0.1, self.termination_grace_seconds))
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5.0)


def _drain_stream(
    stream: BinaryIO | None,
    tail: _BoundedByteTail,
    *,
    log_path: Path | None,
    tee_stream: BinaryIO | None,
) -> None:
    """持续排空一个 pipe，写入日志并保留有界 tail。"""

    if stream is None:
        return
    log_stream: BinaryIO | None = None
    try:
        if log_path is not None:
            log_stream = log_path.open("ab", buffering=0)
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            tail.append(chunk)
            if log_stream is not None:
                log_stream.write(chunk)
            if tee_stream is not None:
                with contextlib.suppress(Exception):
                    tee_stream.write(chunk)
                    tee_stream.flush()
    finally:
        if log_stream is not None:
            log_stream.close()


def _join_drain_threads(*threads: Thread) -> None:
    """等待 pipe 排空线程退出。"""

    for thread in threads:
        thread.join(timeout=10.0)


__all__ = ["ProcessTreeResult", "ProcessTreeSupervisor"]
