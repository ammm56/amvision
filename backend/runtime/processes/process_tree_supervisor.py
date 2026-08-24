"""跨平台子进程树监督、取消、deadline 与有界日志采集。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Thread
import time
from typing import BinaryIO

from backend.runtime.processes.attempt_deadline import AttemptDeadline
from backend.runtime.processes.bounded_log_sink import BoundedByteTail, BoundedLogSink
from backend.runtime.processes.windows_job_bootstrap import (
    WindowsJob,
    build_bootstrap_command,
    release_bootstrap,
)
from backend.service.application.errors import (
    OperationCancelledError,
    OperationTimeoutError,
    ServiceConfigurationError,
)


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
    stdout_log_error: str | None = None
    stderr_log_error: str | None = None

    def to_completed_process(self) -> subprocess.CompletedProcess[str]:
        """转换成兼容既有构建器的 ``CompletedProcess``。"""

        return subprocess.CompletedProcess(
            list(self.command),
            self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class ProcessTreeSupervisor:
    """运行命令，持续排空日志并监督完整进程树生命周期。"""

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        deadline: AttemptDeadline | None = None,
        termination_grace_seconds: float = 5.0,
        force_kill_wait_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        tail_capacity_bytes: int = 64 * 1024,
        log_capacity_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        """初始化监督参数；timeout 与 deadline 只能指定一个。"""

        if (timeout_seconds is None) == (deadline is None):
            raise ValueError("timeout_seconds 与 deadline 必须且只能指定一个")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self.deadline = deadline or AttemptDeadline.from_timeout(float(timeout_seconds))
        self.timeout_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else self.deadline.remaining_seconds()
        )
        self.termination_grace_seconds = max(0.0, float(termination_grace_seconds))
        self.force_kill_wait_seconds = max(0.1, float(force_kill_wait_seconds))
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.tail_capacity_bytes = max(1024, int(tail_capacity_bytes))
        self.log_capacity_bytes = max(0, int(log_capacity_bytes))

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        stdout_log_path: Path | None = None,
        stderr_log_path: Path | None = None,
        tee_output: bool = False,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ProcessTreeResult:
        """执行命令并返回有界日志 tail。"""

        normalized_command = tuple(str(part) for part in command)
        if not normalized_command:
            raise ValueError("command 不能为空")
        if self.deadline.expired():
            raise self._build_timeout_error(
                command=normalized_command,
                process_id=None,
                stdout_tail="",
                stderr_tail="",
                stdout_log_path=stdout_log_path,
                stderr_log_path=stderr_log_path,
            )

        popen_kwargs: dict[str, object] = {
            "cwd": str(cwd) if cwd is not None else None,
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "bufsize": 0,
        }
        windows_job: WindowsJob | None = None
        if os.name == "nt":
            popen_kwargs["stdin"] = subprocess.PIPE
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            launched_command = build_bootstrap_command(normalized_command)
        else:
            popen_kwargs["stdin"] = subprocess.DEVNULL
            popen_kwargs["start_new_session"] = True
            launched_command = list(normalized_command)

        started_at = time.monotonic()
        process = subprocess.Popen(launched_command, **popen_kwargs)  # type: ignore[arg-type]
        stdout_tail = BoundedByteTail(self.tail_capacity_bytes)
        stderr_tail = BoundedByteTail(self.tail_capacity_bytes)
        stdout_sink = BoundedLogSink(
            stdout_log_path,
            capacity_bytes=self.log_capacity_bytes,
        )
        stderr_sink = BoundedLogSink(
            stderr_log_path,
            capacity_bytes=self.log_capacity_bytes,
        )
        stdout_thread: Thread | None = None
        stderr_thread: Thread | None = None
        try:
            if os.name == "nt":
                try:
                    windows_job = WindowsJob()
                    windows_job.assign(process)
                    release_bootstrap(process)
                except Exception as error:
                    self._force_terminate_process_tree(process, windows_job=windows_job)
                    raise ServiceConfigurationError(
                        "Windows Job Object bootstrap 初始化失败",
                        details={"process_id": process.pid, "error": str(error)},
                    ) from error

            stdout_thread = Thread(
                target=_drain_stream,
                args=(process.stdout, stdout_tail, stdout_sink),
                kwargs={"tee_stream": sys.stdout.buffer if tee_output else None},
                daemon=True,
                name=f"process-{process.pid}-stdout",
            )
            stderr_thread = Thread(
                target=_drain_stream,
                args=(process.stderr, stderr_tail, stderr_sink),
                kwargs={"tee_stream": sys.stderr.buffer if tee_output else None},
                daemon=True,
                name=f"process-{process.pid}-stderr",
            )
            stdout_thread.start()
            stderr_thread.start()
            returncode = self._wait_for_completion(
                process,
                cancel_requested=cancel_requested,
                command=normalized_command,
                windows_job=windows_job,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                stdout_log_path=stdout_log_path,
                stderr_log_path=stderr_log_path,
                stdout_sink=stdout_sink,
                stderr_sink=stderr_sink,
            )
            _join_drain_threads(stdout_thread, stderr_thread)
            return ProcessTreeResult(
                command=normalized_command,
                returncode=returncode,
                stdout=stdout_tail.decode(),
                stderr=stderr_tail.decode(),
                duration_seconds=max(0.0, time.monotonic() - started_at),
                stdout_log_path=stdout_log_path,
                stderr_log_path=stderr_log_path,
                stdout_log_error=stdout_sink.error,
                stderr_log_error=stderr_sink.error,
            )
        finally:
            if process.poll() is None:
                self._stop_process_tree(process, windows_job=windows_job)
            if windows_job is not None:
                windows_job.close()
            stdout_sink.close()
            stderr_sink.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    with contextlib.suppress(Exception):
                        stream.close()
            if stdout_thread is not None and stderr_thread is not None:
                _join_drain_threads(stdout_thread, stderr_thread)

    def _wait_for_completion(
        self,
        process: subprocess.Popen[bytes],
        *,
        cancel_requested: Callable[[], bool] | None,
        command: tuple[str, ...],
        windows_job: WindowsJob | None,
        stdout_tail: BoundedByteTail,
        stderr_tail: BoundedByteTail,
        stdout_log_path: Path | None,
        stderr_log_path: Path | None,
        stdout_sink: BoundedLogSink,
        stderr_sink: BoundedLogSink,
    ) -> int:
        """轮询取消与 deadline，避免给任一 helper 重新分配预算。"""

        while True:
            if cancel_requested is not None and cancel_requested():
                self._stop_process_tree(process, windows_job=windows_job)
                raise OperationCancelledError(
                    "受监督进程执行已取消",
                    details=self._build_diagnostics(
                        command=command,
                        process_id=process.pid,
                        stdout_tail=stdout_tail.decode(),
                        stderr_tail=stderr_tail.decode(),
                        stdout_log_path=stdout_log_path,
                        stderr_log_path=stderr_log_path,
                        stdout_log_error=stdout_sink.error,
                        stderr_log_error=stderr_sink.error,
                    ),
                )
            remaining = self.deadline.remaining_seconds()
            if remaining <= 0:
                self._stop_process_tree(process, windows_job=windows_job)
                raise self._build_timeout_error(
                    command=command,
                    process_id=process.pid,
                    stdout_tail=stdout_tail.decode(),
                    stderr_tail=stderr_tail.decode(),
                    stdout_log_path=stdout_log_path,
                    stderr_log_path=stderr_log_path,
                    stdout_log_error=stdout_sink.error,
                    stderr_log_error=stderr_sink.error,
                )
            try:
                return process.wait(timeout=min(self.poll_interval_seconds, remaining))
            except subprocess.TimeoutExpired:
                continue

    def _stop_process_tree(
        self,
        process: subprocess.Popen[bytes],
        *,
        windows_job: WindowsJob | None,
    ) -> None:
        """先请求协作退出，grace 到期后强制终止完整进程树。"""

        if process.poll() is not None:
            return
        if os.name == "nt":
            with contextlib.suppress(Exception):
                process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=max(0.1, self.termination_grace_seconds))
            return
        except subprocess.TimeoutExpired:
            self._force_terminate_process_tree(process, windows_job=windows_job)

    def _force_terminate_process_tree(
        self,
        process: subprocess.Popen[bytes],
        *,
        windows_job: WindowsJob | None,
    ) -> None:
        """强制终止完整进程树并有界等待完成。"""

        if os.name == "nt":
            if windows_job is not None:
                windows_job.terminate(exit_code=1)
            else:
                with contextlib.suppress(Exception):
                    process.kill()
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=self.force_kill_wait_seconds)

    def _build_timeout_error(
        self,
        *,
        command: tuple[str, ...],
        process_id: int | None,
        stdout_tail: str,
        stderr_tail: str,
        stdout_log_path: Path | None,
        stderr_log_path: Path | None,
        stdout_log_error: str | None = None,
        stderr_log_error: str | None = None,
    ) -> OperationTimeoutError:
        """建立统一的受监督进程超时错误。"""

        return OperationTimeoutError(
            "受监督进程树执行超时",
            details=self._build_diagnostics(
                command=command,
                process_id=process_id,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                stdout_log_path=stdout_log_path,
                stderr_log_path=stderr_log_path,
                stdout_log_error=stdout_log_error,
                stderr_log_error=stderr_log_error,
                extra={
                    "timeout_seconds": self.timeout_seconds,
                    "deadline_at": self.deadline.deadline_at_iso,
                },
            ),
        )

    @staticmethod
    def _build_diagnostics(
        *,
        command: tuple[str, ...],
        process_id: int | None,
        stdout_tail: str,
        stderr_tail: str,
        stdout_log_path: Path | None,
        stderr_log_path: Path | None,
        stdout_log_error: str | None,
        stderr_log_error: str | None,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """建立不包含无限日志内容的诊断数据。"""

        return {
            "process_id": process_id,
            "command": list(command),
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "stdout_log_path": str(stdout_log_path) if stdout_log_path else None,
            "stderr_log_path": str(stderr_log_path) if stderr_log_path else None,
            "stdout_log_error": stdout_log_error,
            "stderr_log_error": stderr_log_error,
            **(extra or {}),
        }


def _drain_stream(
    stream: BinaryIO | None,
    tail: BoundedByteTail,
    sink: BoundedLogSink,
    *,
    tee_stream: BinaryIO | None,
) -> None:
    """持续排空一个 pipe，文件到达上限或写失败后仍继续读取。"""

    if stream is None:
        return
    sink.open()
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            tail.append(chunk)
            sink.write(chunk)
            if tee_stream is not None:
                with contextlib.suppress(Exception):
                    tee_stream.write(chunk)
                    tee_stream.flush()
    finally:
        sink.close()


def _join_drain_threads(*threads: Thread) -> None:
    """等待 pipe 排空线程退出。"""

    for thread in threads:
        thread.join(timeout=10.0)


__all__ = ["ProcessTreeResult", "ProcessTreeSupervisor"]
