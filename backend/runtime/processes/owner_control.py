"""外部控制仅结束经核实的 owner；后代由 OwnershipScope 单独回收。"""

import psutil
import math
from time import monotonic, sleep
from backend.runtime.processes.birth_identity import read_process_birth_identity


def stop_owner(identity: dict, *, timeout: float) -> None:
    """只操作内核出生标识匹配的 owner，不把它退出当作后代退出证据。"""
    try:
        process = psutil.Process(int(identity["pid"]))
        if read_process_birth_identity(process.pid) != identity["birth_identity"]:
            raise RuntimeError("owner 身份已经变化，拒绝停止")
        process.kill()
        wait_owner_exit(identity, timeout=timeout)
    except psutil.NoSuchProcess:
        return


def wait_owner_exit(identity: dict, *, timeout: float) -> None:
    """确认指定代次已退出；非子进程的 zombie 无执行资源，不等待其父进程 waitpid。"""
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("timeout 必须为有限非负数")
    pid = int(identity["pid"])
    expected = identity["birth_identity"]
    deadline = monotonic() + timeout
    while True:
        try:
            process = psutil.Process(pid)
            if read_process_birth_identity(pid) != expected or process.status() == psutil.STATUS_ZOMBIE:
                return
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise psutil.TimeoutExpired(timeout, pid=pid)
        sleep(min(0.01, remaining))
