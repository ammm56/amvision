"""真实 Windows 控制台中断不能依赖子进程自行退出才生效。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import socket
import time

import psutil
import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows 控制台事件")
@pytest.mark.parametrize("mode", ["idle", "http", "http-reload"])
def test_launcher_ctrl_c_reaps_managed_group(tmp_path, mode):
    """一次 Ctrl+C 返回 130，并经既有归属组回收忽略 Ctrl+C 的子进程。"""
    from backend.runtime.processes.windows_job import WindowsJob
    from tests.launcher_console_fixture import STARTUP_TIMEOUT, SHUTDOWN_TIMEOUT

    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    with (tmp_path / "console.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("launcher_console_fixture.py")),
             "controller", str(tmp_path), mode],
            stdin=subprocess.PIPE, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        job = WindowsJob()
        try:
            job.assign_handle(int(process._handle))
            process.stdin.write(b"1")
            process.stdin.flush()
            # 重载包含两次冷启动，外层期限须覆盖两个阶段及独立退出预算。
            starts = 2 if mode == "http-reload" else 1
            process.wait(timeout=starts * STARTUP_TIMEOUT + SHUTDOWN_TIMEOUT + 15)
            assert process.returncode == 0, (tmp_path / "console.log").read_text("utf-8", errors="replace")
            result = json.loads((tmp_path / "result.json").read_text("utf-8"))
            assert result["returncode"] == 130, result
            assert result["reloaded"] == (mode == "http-reload")
            if result["child_pid"] is not None:
                assert not psutil.pid_exists(result["child_pid"]), result
            else:
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", result["port"]))
            # 新控制台的 conhost 可晚于 controller 退出；有界等待整个 Job，
            # 不过滤系统进程，也不把根进程退出等同于全部后代已回收。
            deadline = time.monotonic() + 5
            while job.members() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not job.members(), "启动器退出后仍遗留服务或重载子进程"
        finally:
            job.terminate()
            process.wait(timeout=10)
            process.stdin.close()
            job.close()
