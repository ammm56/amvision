"""用真实进程核对发行目录占用保护、进程身份和整棵树回收。"""

import subprocess
import sys
import os
from types import SimpleNamespace
from pathlib import Path

import pytest

from backend.maintenance.release_process_guard import require_release_stopped
from tests.integration.release_deployment_recovery import verify_owned_deployment_recovery


def test_fault_injection_rejects_process_outside_owned_release(tmp_path: Path) -> None:
    """即使 API 返回 PID，也不能终止隔离目录以外的进程。"""
    client = SimpleNamespace(get=lambda _: {"desired_state": "running", "auto_restart": True,
                                           "process_id": os.getpid()})
    with pytest.raises(ValueError, match="拒绝对隔离发行目录之外"):
        verify_owned_deployment_recovery(client, route="/deployment-test", release_root=tmp_path)


def test_release_in_use_is_rejected_before_rebuild(tmp_path: Path) -> None:
    """进程只通过 cwd 使用目录时也必须拒绝覆盖，停止后可继续。"""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path)
    try:
        with pytest.raises(ValueError, match="发行目录仍有运行进程"):
            require_release_stopped(tmp_path)
    finally:
        process.kill()
        process.wait(timeout=10)
    require_release_stopped(tmp_path)
