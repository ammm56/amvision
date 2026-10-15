"""multiprocessing spawn 的受管启动门，与命令进程复用同一组归属。"""

from __future__ import annotations

import multiprocessing
import math
from multiprocessing.context import SpawnContext, SpawnProcess
import os
from pathlib import Path
import subprocess
import sys
from threading import RLock
import time
from types import SimpleNamespace
from uuid import uuid4

from backend.runtime.processes.ownership import OwnershipScope, SCOPE_ENV, PARENT_ENV
from backend.runtime.processes.process_group import ProcessGroup


class ManagedSpawnProcess(SpawnProcess):
    """仅在父进程完成归属登记后调用 target；停止必须回收整个子域。"""

    def start(self):
        """spawn 的准备阶段不执行 target，父端绑定成功后发送放行令牌。"""
        self._check_closed()
        if self._popen is not None:
            raise RuntimeError("同一个进程对象不能重复启动")
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        ready_receiver, ready_sender = context.Pipe(duplex=False)
        self._start_gate = receiver
        self._ready_gate = ready_sender
        self._scope_path = str(OwnershipScope.current().root)
        self._group_id = uuid4().hex
        self._group = None
        keepalive_receiver, keepalive_sender = context.Pipe(duplex=False)
        self._owner_watch = keepalive_receiver
        parent = os.environ.get(PARENT_ENV)
        released = False
        try:
            super().start()
            receiver.close()
            ready_sender.close()
            keepalive_receiver.close()
            self._owner_sender = keepalive_sender
            self._stop_lock = RLock()
            if not ready_receiver.poll(30) or ready_receiver.recv_bytes() != b"ready":
                raise TimeoutError("spawn 进程未建立启动门")
            handle = self._popen._handle if os.name == "nt" else None
            self._group = ProcessGroup(
                SimpleNamespace(
                    pid=self.pid,
                    _handle=handle,
                    anchor_path=self._scope_path_as_path() / f"{self._group_id}.anchor",
                )
            )
            OwnershipScope(self._scope_path_as_path()).register(
                self._group_id, self._group, parent
            )
            sender.send_bytes(b"start")
            released = True
        except BaseException:
            if self._popen is not None:
                if self._group is not None:
                    self._group.signal(force=True)
                super().kill()
                super().join(10)
            if self._group is not None:
                self._group.wait_empty(10)
                OwnershipScope(self._scope_path_as_path()).retire(self._group_id)
                self._group.close()
            raise
        finally:
            sender.close()
            ready_receiver.close()
            receiver.close()
            ready_sender.close()
            keepalive_receiver.close()
            if not released:
                keepalive_sender.close()

    def _scope_path_as_path(self):
        """运行时路径在 spawn pickle 中只传字符串。"""
        return Path(self._scope_path)

    def run(self):
        """子端在 target 之前建立 POSIX 组并等待父端登记。"""
        if os.name != "nt":
            os.setsid()
        os.environ[SCOPE_ENV] = self._scope_path
        os.environ[PARENT_ENV] = self._group_id
        if os.name != "nt":
            subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("posix_group_guardian.py")),
                ],
                stdin=self._owner_watch.fileno(),
                stdout=subprocess.DEVNULL,
            )
        self._owner_watch.close()
        self._ready_gate.send_bytes(b"ready")
        self._ready_gate.close()
        try:
            if self._start_gate.recv_bytes() != b"start":
                return
        except EOFError:
            return
        finally:
            self._start_gate.close()
        super().run()

    def stop_group(self, timeout: float = 10, *, force: bool = True):
        """清空整个登记子域；根进程退出不能提前归还 GPU/IPC 资源。"""
        if getattr(self, "_group", None) is None:
            return
        with self._stop_lock:
            self._stop_group(timeout, force=force)

    def _stop_group(self, timeout: float, *, force: bool) -> None:
        """序列化 shutdown、监视线程和显式 close 的共同回收。"""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("停止预算必须为有限非负数")
        if self._group._closed:
            return
        scope = OwnershipScope(self._scope_path_as_path())
        deadline = time.perf_counter() + timeout
        if force:
            scope.stop(root_id=self._group_id, timeout=timeout)
        else:
            scope.require_empty(self._group_id)
        self._group.wait_empty(max(0, deadline - time.perf_counter()))
        super().join(max(0, deadline - time.perf_counter()))
        scope.require_empty(self._group_id)
        scope.retire(self._group_id)
        self._group.close()
        self._owner_sender.close()

    def terminate(self):
        """terminate 的目标是平台组，不是单个根 PID。"""
        self.stop_group()

    def kill(self):
        """kill 与 terminate 共用整组强停契约。"""
        self.stop_group()

    def close(self):
        """只有确认全组清空后才能关闭 multiprocessing 句柄。"""
        self.stop_group()
        super().close()


class ManagedSpawnContext(SpawnContext):
    """保持 Queue/Pipe/Event 的 spawn 上下文，只统一 Process 生命周期。"""

    Process = ManagedSpawnProcess


def managed_spawn_context():
    """为业务监督器提供平台无关的同一 spawn 上下文。"""
    return ManagedSpawnContext()
