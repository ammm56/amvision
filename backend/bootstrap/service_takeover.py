"""同一目录中独立服务的进程身份校验、停止请求和有界接替。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Callable

import psutil


class ServiceTakeoverError(RuntimeError):
    """旧服务身份不匹配或未完全退出，禁止启动新一代。"""


def _has_module(process: psutil.Process, module: str) -> bool:
    """要求准确的 python -m 模块入口，不按进程名模糊匹配。"""
    args = process.cmdline()
    return any(args[i:i + 2] == ["-m", module] for i in range(len(args) - 1))


def _request_path(lock_path: Path, pid: int) -> Path:
    """停止请求与具体锁及 PID 绑定，内容再校验进程创建时间。"""
    return lock_path.with_name(f"{lock_path.name}.stop-{pid}.json")


class ServiceStopListener:
    """监听仅针对当前进程身份的本地停止请求，不暴露网络端点。"""

    def __init__(self, lock_path: Path, callback: Callable[[], None]):
        """保存锁位置、停止回调和本进程身份。"""
        self.path = _request_path(lock_path.resolve(), os.getpid())
        self.created = psutil.Process().create_time()
        self.callback = callback
        self.closed = Event()
        self.thread = Thread(target=self._run, daemon=True, name="service-stop-listener")

    def __enter__(self):
        """启动轻量停止监听。"""
        self.thread.start()
        return self

    def _run(self):
        """忽略旧 PID 或不完整请求；匹配后只通知一次正常退出。"""
        while not self.closed.wait(0.2):
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if value == {"pid": os.getpid(), "create_time": self.created}:
                    self.callback()
                    return
            except (OSError, ValueError):
                continue

    def __exit__(self, *_args):
        """停止监听并清理本进程的请求文件。"""
        self.closed.set()
        self.thread.join(timeout=1)
        self.path.unlink(missing_ok=True)


def replace_service_owner(
    *, lock_path: Path, module: str, owner_pid: int | None = None,
    owner_started_ns: int | None = None, timeout_seconds: float = 30,
) -> int | None:
    """只接替更旧、同目录同解释器且实际打开冲突锁的同类服务。

    新版本先响应本地停止请求；旧版本或超时进程再按经验证的进程树结束。
    不接替 full 管理的单个子服务，应由新 full 根进程替换旧 full。
    """
    path = lock_path.resolve()
    current = psutil.Process()
    if not _has_module(current, module):
        raise ServiceTakeoverError(f"当前进程不是标准 {module} 入口，拒绝接管")
    try:
        candidates = [psutil.Process(owner_pid)] if owner_pid else psutil.process_iter()
    except psutil.NoSuchProcess:
        return None
    matches = []
    for process in candidates:
        try:
            if process.pid == current.pid or not _has_module(process, module):
                continue
            if Path(process.cwd()).resolve() != Path(current.cwd()).resolve() or Path(process.exe()).resolve() != Path(current.exe()).resolve():
                continue
            if not any(Path(item.path).resolve() == path for item in process.open_files()):
                continue
            if owner_started_ns is not None and abs(process.create_time() - owner_started_ns / 1e9) > 0.01:
                raise ServiceTakeoverError("owner PID 已复用，拒绝接管")
            if process.create_time() >= current.create_time():
                raise ServiceTakeoverError("当前服务不比 owner 更新，拒绝反向接管")
            parents = process.parents()
            if any(Path(arg).name == "start_amvision_full.py" for parent in parents for arg in parent.cmdline()):
                raise ServiceTakeoverError("旧服务由 full 启动器管理，请重新运行 full 启动器接替整套服务")
            if process.pid in {p.pid for p in current.parents()}:
                raise ServiceTakeoverError("不能接管当前进程的祖先进程")
            matches.append(process)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied as error:
            if owner_pid:
                raise ServiceTakeoverError("无法核实 owner 进程身份，拒绝接管") from error
    if not matches:
        if owner_pid and psutil.pid_exists(owner_pid):
            raise ServiceTakeoverError("占用者与当前服务的目录、解释器、入口或锁句柄不匹配")
        return None
    if len(matches) != 1:
        raise ServiceTakeoverError("存在多个候选 owner，拒绝不明确的接管")
    target = matches[0]
    created = target.create_time()
    descendants = target.children(recursive=True)
    request = _request_path(path, target.pid)
    request.write_text(json.dumps({"pid": target.pid, "create_time": created}), encoding="utf-8")
    try:
        # 优先让新版本按正常停机顺序保存状态、回收模型和 Worker。
        try:
            target.wait(timeout=min(5, timeout_seconds))
        except psutil.TimeoutExpired:
            if target.is_running() and target.create_time() == created:
                descendants = target.children(recursive=True)
                target.terminate()
        deadline = monotonic() + timeout_seconds
        for process in [target, *reversed(descendants)]:
            if process.is_running():
                try:
                    process.terminate()
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    pass
        _, alive = psutil.wait_procs([target, *descendants], timeout=max(0.1, deadline - monotonic()))
        for process in alive:
            process.kill()
        _, alive = psutil.wait_procs(alive, timeout=5)
        if alive:
            raise ServiceTakeoverError(f"旧服务未完全退出：{[p.pid for p in alive]}")
        print(f"已退出旧 {module}（PID={target.pid}），继续启动新服务。", flush=True)
        return target.pid
    finally:
        request.unlink(missing_ok=True)
