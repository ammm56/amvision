"""独立服务同目录接替的真实子进程验收，只操作测试自己的锁和进程。"""

from pathlib import Path
import subprocess
import sys
import time
import os
import json
import shutil

import psutil
import pytest


@pytest.mark.parametrize("legacy", [False, True])
def test_new_service_replaces_old_owner_and_releases_lock(tmp_path, legacy):
    """真实停止旧 owner，确认旧进程退出后新进程取得相同锁。"""
    lock = tmp_path / "owner.lock"
    ready = tmp_path / "ready"
    command = [sys.executable, "-m", "tests.test_service_takeover", str(lock), str(ready)]
    owner = subprocess.Popen(command + (["legacy"] if legacy else []), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            assert owner.poll() is None
            time.sleep(0.05)
        assert ready.exists()
        replacement = subprocess.run(command + ["replace", str(owner.pid)], capture_output=True, timeout=20)
        assert replacement.returncode == 0, replacement.stderr.decode(errors="replace")
        owner.wait(timeout=5)
        assert legacy or owner.returncode == 0
        assert b"replacement acquired" in replacement.stdout
    finally:
        if owner.poll() is None:
            owner.terminate()
            owner.wait(timeout=5)


def test_takeover_rejects_non_service_caller(tmp_path):
    """pytest 自身不属于服务入口，不能结束任何 owner。"""
    import pytest
    from backend.bootstrap.service_takeover import replace_service_owner
    with pytest.raises(RuntimeError, match="不是标准"):
        replace_service_owner(lock_path=tmp_path / "owner", module="backend.inference_daemon.main", owner_pid=os.getpid())


def test_actual_daemon_latest_start_replaces_old_daemon(tmp_path):
    """运行两个真实 daemon CLI，使用隔离数据库和 buffers 验证正常接替。"""
    from backend.service.infrastructure.ipc.local_message.paths import build_inference_mailbox_paths
    from backend.bootstrap.service_takeover import _request_path
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    environment["AMVISION_DATABASE__URL"] = f"sqlite:///{(tmp_path / 'data/daemon.db').as_posix()}"
    environment["AMVISION_LOCAL_MEMORY__ROOT_DIR"] = str(tmp_path / "buffers")
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "config/backend-service.json", tmp_path / "config/backend-service.json")
    command = [sys.executable, "-m", "backend.inference_daemon.main"]
    processes = []
    logs = []
    try:
        for index in range(2):
            log_path = tmp_path / f"daemon-{index}.log"
            handle = log_path.open("wb")
            logs.append(handle)
            process = subprocess.Popen(command, cwd=tmp_path, env=environment, stdout=handle, stderr=subprocess.STDOUT)
            processes.append(process)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                content = log_path.read_text(encoding="utf-8", errors="replace")
                assert process.poll() is None, content
                if "inference-daemon ready" in content:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError(content)
        assert processes[0].wait(timeout=5) == 0
        assert processes[1].poll() is None
    finally:
        lock = build_inference_mailbox_paths(buffers_root=tmp_path / "buffers").owner_lock_path
        for process in reversed(processes):
            if process.poll() is None:
                _request_path(lock, process.pid).write_text(json.dumps({"pid": process.pid, "create_time": psutil.Process(process.pid).create_time()}))
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
        for handle in logs:
            handle.close()


if __name__ == "__main__":
    from threading import Event
    from backend.bootstrap.service_takeover import ServiceStopListener, replace_service_owner
    from backend.service.infrastructure.ipc.mmap_primitives import acquire_mmap_owner_lock
    lock_path, ready_path = Path(sys.argv[1]), Path(sys.argv[2])
    if len(sys.argv) > 3 and sys.argv[3] == "replace":
        pid = int(sys.argv[4])
        replace_service_owner(lock_path=lock_path, module="tests.test_service_takeover", owner_pid=pid, owner_started_ns=int(psutil.Process(pid).create_time() * 1e9))
        handle = acquire_mmap_owner_lock(lock_path)
        handle.release()
        print("replacement acquired")
    else:
        stop = Event()
        handle = acquire_mmap_owner_lock(lock_path)
        try:
            if len(sys.argv) > 3 and sys.argv[3] == "legacy":
                ready_path.write_text(str(os.getpid()))
                stop.wait(30)
            else:
                with ServiceStopListener(lock_path, stop.set):
                    ready_path.write_text(str(os.getpid()))
                    stop.wait(30)
        finally:
            handle.release()
