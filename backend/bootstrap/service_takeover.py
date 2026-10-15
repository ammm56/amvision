"""同一目录中独立服务的进程身份校验、停止请求和有界接替。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event, Thread
from typing import Callable

import psutil
from backend.runtime.processes.ownership import OwnershipScope, PARENT_ENV
from backend.runtime.processes.owner_control import stop_owner, wait_owner_exit
from backend.runtime.processes.birth_identity import read_process_birth_identity, birth_identity_is_newer


class ServiceTakeoverError(RuntimeError):
    """旧服务身份不匹配或未完全退出，禁止启动新一代。"""


def _has_module(process: psutil.Process, module: str) -> bool:
    """要求准确的 python -m 模块入口，不按进程名模糊匹配。"""
    args = process.cmdline()
    return any(args[i:i + 2] == ["-m", module] for i in range(len(args) - 1))


def _has_full_launcher_ancestor(process: psutil.Process) -> bool:
    """检查应用祖先；到达 Windows 系统宿主后结束，不查询受保护的系统命令行。"""
    system_root = os.environ.get("SystemRoot") if os.name == "nt" else None
    system_directory = (Path(system_root) / "System32").resolve() if system_root else None
    for parent in process.parents():
        if system_directory is not None:
            executable = Path(parent.exe()).resolve()
            if executable.parent == system_directory and executable.name.casefold() in {
                "svchost.exe", "services.exe", "wininit.exe", "winlogon.exe", "smss.exe",
            }:
                return False
        # 未知或 Python 应用祖先仍须可核实；不能把 AccessDenied 当作独立服务。
        if any(Path(arg).name == "start_amvision_full.py" for arg in parent.cmdline()):
            return True
    return False


def _request_path(lock_path: Path, pid: int) -> Path:
    """停止请求与具体锁及 PID 绑定，内容再校验内核出生标识。"""
    return lock_path.with_name(f"{lock_path.name}.stop-{pid}.json")


class ServiceStopListener:
    """监听仅针对当前进程身份的本地停止请求，不暴露网络端点。"""

    def __init__(self, lock_path: Path, callback: Callable[[], None]):
        """保存锁位置、停止回调和本进程身份。"""
        self.path = _request_path(lock_path.resolve(), os.getpid())
        self.birth_identity = read_process_birth_identity(os.getpid())
        self.callback = callback
        self.closed = Event()
        self.thread = Thread(target=self._run, daemon=True, name="service-stop-listener")
        self.ownership_path = self.path.with_suffix(".ownership.json")

    def __enter__(self):
        """启动轻量停止监听。"""
        scope = OwnershipScope.current()
        self.ownership_path.write_text(json.dumps({"format_id": "amvision.service-ownership.v2",
            "pid": os.getpid(), "birth_identity": self.birth_identity, "scope": str(scope.root),
            "group_id": os.environ.get(PARENT_ENV)}), encoding="utf-8")
        self.thread.start()
        return self

    def _run(self):
        """忽略旧 PID 或不完整请求；匹配后只通知一次正常退出。"""
        while not self.closed.wait(0.2):
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if value == {"pid": os.getpid(), "birth_identity": self.birth_identity}:
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
    timeout_seconds: float = 30,
) -> int | None:
    """只接替更旧、同目录同解释器且实际打开冲突锁的同类服务。

    只接受启动时的归属登记；停止请求超时后按登记组结束，不回收旧快照。
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
            if not birth_identity_is_newer(read_process_birth_identity(current.pid), read_process_birth_identity(process.pid)):
                raise ServiceTakeoverError("当前服务不比 owner 更新，拒绝反向接管")
            if _has_full_launcher_ancestor(process):
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
    birth_identity = read_process_birth_identity(target.pid)
    request = _request_path(path, target.pid)
    ownership_path = request.with_suffix(".ownership.json")
    try:
        ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        if (ownership.get("format_id"), ownership.get("pid"), ownership.get("birth_identity")) != ("amvision.service-ownership.v2", target.pid, birth_identity):
            raise ValueError("服务归属身份不匹配")
        scope = OwnershipScope(Path(ownership["scope"]))
        scope.validate()
    except (OSError, ValueError, KeyError) as error:
        raise ServiceTakeoverError("服务缺少可验证的启动归属，拒绝接替") from error
    request.write_text(json.dumps({"pid": target.pid, "birth_identity": birth_identity}), encoding="utf-8")
    try:
        # 保留完整协作窗口；旧 root 退出后仍须核对登记的全部组。
        try:
            wait_owner_exit({"pid": target.pid, "birth_identity": birth_identity}, timeout=timeout_seconds)
        except psutil.TimeoutExpired:
            if ownership["group_id"] is None:
                scope.seal()
                stop_owner({"pid": target.pid, "birth_identity": birth_identity}, timeout=5)
            scope.stop(root_id=ownership["group_id"], timeout=5)
        scope.require_empty(ownership["group_id"])
        ownership_path.unlink(missing_ok=True)
        print(f"已退出旧 {module}（PID={target.pid}），继续启动新服务。", flush=True)
        return target.pid
    finally:
        request.unlink(missing_ok=True)
