"""跨平台进程树监督器测试。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from backend.service.application.errors import OperationTimeoutError
from backend.workers.shared.process_tree_supervisor import ProcessTreeSupervisor


def test_process_tree_supervisor_drains_large_output_to_logs(tmp_path: Path) -> None:
    """验证大量 stdout/stderr 被持续排空，内存只保留有界 tail。"""

    stdout_log = tmp_path / "stdout.log"
    stderr_log = tmp_path / "stderr.log"
    result = ProcessTreeSupervisor(
        timeout_seconds=10.0,
        tail_capacity_bytes=4096,
    ).run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.write('A' * 200000 + '\\nLAST-STDOUT\\n'); "
                "sys.stderr.write('B' * 200000 + '\\nLAST-STDERR\\n')"
            ),
        ],
        stdout_log_path=stdout_log,
        stderr_log_path=stderr_log,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "LAST-STDOUT"
    assert result.stderr.splitlines()[-1] == "LAST-STDERR"
    assert len(result.stdout.encode()) <= 4096
    assert len(result.stderr.encode()) <= 4096
    assert stdout_log.stat().st_size > 200000
    assert stderr_log.stat().st_size > 200000


def test_process_tree_supervisor_enforces_hard_timeout(tmp_path: Path) -> None:
    """验证 hard deadline 到达后返回正式 timeout 错误并保留日志位置。"""

    stdout_log = tmp_path / "stdout.log"
    started_at = time.monotonic()
    with pytest.raises(OperationTimeoutError) as exc_info:
        ProcessTreeSupervisor(
            timeout_seconds=0.25,
            termination_grace_seconds=0.1,
        ).run(
            [
                sys.executable,
                "-c",
                "import time; print('started', flush=True); time.sleep(60)",
            ],
            stdout_log_path=stdout_log,
        )

    assert time.monotonic() - started_at < 5.0
    assert exc_info.value.code == "operation_timeout"
    assert exc_info.value.details["timeout_seconds"] == 0.25
    assert exc_info.value.details["stdout_log_path"] == str(stdout_log)
    assert "started" in stdout_log.read_text(encoding="utf-8")


def test_process_tree_supervisor_terminates_descendant_process(tmp_path: Path) -> None:
    """验证 timeout 清理的不只是根进程，还包括其子进程。"""

    marker_path = tmp_path / "descendant-finished.txt"
    child_code = (
        "import pathlib,time; time.sleep(2); "
        f"pathlib.Path({str(marker_path)!r}).write_text('alive')"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(60)"
    )

    with pytest.raises(OperationTimeoutError):
        ProcessTreeSupervisor(
            timeout_seconds=0.25,
            termination_grace_seconds=0.1,
        ).run([sys.executable, "-c", parent_code])

    time.sleep(2.25)
    assert not marker_path.exists()


def test_process_tree_supervisor_returns_nonzero_without_raising() -> None:
    """验证业务命令失败由调用方解释，监督器仍返回日志和退出码。"""

    result = ProcessTreeSupervisor(timeout_seconds=5.0).run(
        [
            sys.executable,
            "-c",
            "import sys; print('failure', file=sys.stderr); sys.exit(7)",
        ]
    )

    assert result.returncode == 7
    assert result.stderr == f"failure{os.linesep}"
    completed = result.to_completed_process()
    assert isinstance(completed, subprocess.CompletedProcess)
    assert completed.returncode == 7
