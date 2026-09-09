"""HTTP 故障的有界整栈恢复协调；只控制已拥有的进程，绝不删除 mmap。"""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import time
from typing import Callable

import psutil


class ServiceRecoveryRequired(RuntimeError):
    """持续 HTTP 故障需要进入唯一恢复协调器。"""


class RecoveryBlocked(RuntimeError):
    """身份、排空或资源清理无法确认，禁止创建下一代。"""


class RecoveryBudget:
    """10 分钟内最多三次，短暂运行不能清空历史预算。"""

    def __init__(self):
        """只保留窗口内最多三个 monotonic 时间。"""
        self.attempts: deque[float] = deque()

    def reserve(self, now: float) -> float:
        """登记一次恢复，并返回 2/5/15 秒退避。"""
        while self.attempts and now - self.attempts[0] >= 600:
            self.attempts.popleft()
        if len(self.attempts) >= 3:
            raise RecoveryBlocked("10 分钟内恢复已达到 3 次，停止自动尝试")
        self.attempts.append(now)
        return (2., 5., 15.)[len(self.attempts) - 1]


def wait_until(predicate: Callable[[], bool], check_shutdown: Callable[[], None],
               *, timeout: float, description: str) -> None:
    """所有等待均有期限，人工停止优先于恢复。"""
    deadline = time.monotonic() + timeout
    while True:
        check_shutdown()
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise RecoveryBlocked(description)
        time.sleep(.2)


def drain_owned_stack(*, components: list, identity, directory: Path,
                      check_shutdown: Callable[[], None]) -> None:
    """按消费者、daemon、service/Broker 顺序验证正常退出，不强杀。"""
    from common import process_identity_matches, read_process_identity, write_full_json

    service = next(item.process for item in components if item.name == "backend-service")
    if service is None or service.poll() is not None:
        raise RecoveryBlocked("服务已退出，无法获得排空确认")
    try:
        actual = psutil.Process(identity.pid)
        if service.pid not in {p.pid for p in actual.parents()} and actual.pid != service.pid:
            raise RecoveryBlocked("HTTP 服务已不属于受管组件")
        owned = {}
        for component in components:
            if component.process is None or component.process.poll() is not None:
                continue
            root = psutil.Process(component.process.pid)
            for process in [root, *root.children(recursive=True)]:
                owned[process.pid] = read_process_identity(process.pid)
    except psutil.Error as error:
        raise RecoveryBlocked("无法核实受管进程树") from error

    last_status = {}

    def service_phase(expected: str) -> bool:
        """校验显式阶段确认；仅进程退出不等于释放资源成功。"""
        nonlocal last_status
        path = directory / f"{identity.instance_id}.status.json"
        try:
            if path.stat().st_size > 4096:
                raise RecoveryBlocked("排空确认容量无效")
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if state.get("format_id") != "amvision.http-recovery.v1" or (state.get("instance_id"), state.get("pid")) != (identity.instance_id, identity.pid):
            raise RecoveryBlocked("排空确认身份不匹配")
        if state.get("phase") == "failed":
            raise RecoveryBlocked(str(state.get("error")))
        last_status = state
        return state.get("phase") == expected

    def command(action: str) -> None:
        """每次控制前重验 PID、创建时间、路径与命令行。"""
        if not process_identity_matches(owned[identity.pid]):
            raise RecoveryBlocked("HTTP 服务进程身份已改变")
        write_full_json(directory / f"{identity.instance_id}.request.json", {
            "format_id": "amvision.http-recovery.v1", "instance_id": identity.instance_id,
            "pid": identity.pid, "action": action,
        })

    command("drain")
    wait_until(lambda: service_phase("drained"), check_shutdown, timeout=60,
               description="Runtime/Trigger 未在期限内排空，保留旧资源，禁止重启")
    workers = [item.process for item in components if item.is_worker and item.process is not None]
    wait_until(lambda: all(p.poll() is not None for p in workers), check_shutdown, timeout=30,
               description="后台任务尚未结束，禁止重启")
    if any(p.returncode != 0 for p in workers):
        raise RecoveryBlocked("Worker 未正常退出，无法确认在途任务终态，禁止自动重启")

    daemon = next(item.process for item in components if item.name == "inference-daemon")
    if daemon is None or daemon.poll() is not None:
        raise RecoveryBlocked("daemon 未提供本次正常退出确认")
    matches = []
    for child in psutil.Process(daemon.pid).children(recursive=True):
        args = child.cmdline()
        if any(args[i:i + 2] == ["-m", "backend.inference_daemon.main"] for i in range(len(args) - 1)):
            matches.append(child)
    if len(matches) != 1 or not process_identity_matches(owned.get(matches[0].pid, {})):
        raise RecoveryBlocked("daemon 进程身份无法唯一核实")
    target = matches[0]
    lock = Path(str(last_status.get("inference_owner_lock", "")))
    if not lock.is_absolute() or not any(Path(item.path).resolve() == lock for item in target.open_files()):
        raise RecoveryBlocked("daemon 未持有排空确认中的 owner lock，拒绝发送停止请求")
    request = lock.with_name(f"{lock.name}.stop-{target.pid}.json")
    write_full_json(request, {"pid": target.pid, "create_time": target.create_time()})
    wait_until(lambda: daemon.poll() is not None, check_shutdown, timeout=30,
               description="daemon 未在期限内退出，禁止重启")
    if daemon.returncode != 0:
        raise RecoveryBlocked(f"daemon 异常退出：{daemon.returncode}")
    command("shutdown")
    wait_until(lambda: service_phase("closed") and service.poll() is not None, check_shutdown,
               timeout=30, description="service/Broker 未确认正常关闭，禁止新 owner")
    wait_until(lambda: all(not process_identity_matches(item) for item in owned.values()),
               check_shutdown, timeout=10, description="旧 generation 仍有进程存活")
    wait_until(lambda: not psutil.Process().children(recursive=True), check_shutdown,
               timeout=10, description="Supervisor 仍拥有子进程，禁止创建下一代")
    for suffix in ("request.json", "status.json"):
        (directory / f"{identity.instance_id}.{suffix}").unlink(missing_ok=True)
