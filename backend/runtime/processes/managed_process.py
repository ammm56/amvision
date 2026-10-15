"""复用进程组适配器的统一启动与停止入口。"""

from __future__ import annotations

import os
import math
import subprocess
import time
from threading import RLock
from uuid import uuid4

from backend.runtime.processes.process_group import ProcessGroup
from backend.runtime.processes.ownership import OwnershipScope, SCOPE_ENV, PARENT_ENV
from backend.runtime.processes.bootstrap import (
    build_bootstrap_command,
    release_bootstrap,
)


class ManagedProcess(subprocess.Popen):
    """先建立平台归属再执行命令；保留 Popen 的通信与退出码接口。"""

    def __init__(self, command, *, before_release=None, python_entrypoint=False, **kwargs):
        """before_release 持久化归属；python_entrypoint 在门内直接执行 Python 入口。"""
        if any(
            key in kwargs for key in ("stdin", "start_new_session", "creationflags")
        ):
            raise ValueError("进程归属与控制 stdin 由 ManagedProcess 管理")
        self.group = None
        self._stop_lock = RLock()
        self.scope = OwnershipScope.current()
        self.group_id = uuid4().hex
        self.anchor_path = self.scope.root / f"{self.group_id}.anchor"
        explicit_environment = kwargs.pop("env", None)
        environment = dict(
            os.environ if explicit_environment is None else explicit_environment
        )
        parent_id = os.environ.get(PARENT_ENV)
        environment[SCOPE_ENV] = str(self.scope.root)
        environment[PARENT_ENV] = self.group_id
        super().__init__(
            build_bootstrap_command(command, python_entrypoint=python_entrypoint),
            stdin=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            env=environment,
            **kwargs,
        )
        self._control = self.stdin
        try:
            self.group = ProcessGroup(self)
            self.scope.register(self.group_id, self.group, parent_id)
            if before_release is not None:
                before_release(self)
            release_bootstrap(self)
            # 控制 pipe 不属于目标 stdin；communicate 不能将其提前关闭。
            self.stdin = None
        except BaseException:
            # 目标尚未放行；只结束已知 bootstrap，不存在未受管的目标后代。
            if self.group is not None:
                self.group.signal(force=True)
            super().kill()
            super().wait(timeout=10)
            if self.group is not None:
                self.group.wait_empty(10)
                self.scope.retire(self.group_id)
                self.group.close()
            if self._control is not None:
                self._control.close()
            raise

    def stop(self, *, grace: float = 5, timeout: float = 10) -> None:
        """协作退出后按组强停；同一 deadline 内确认清空才能返回。"""
        with self._stop_lock:
            self._stop(grace=grace, timeout=timeout)

    def _stop(self, *, grace: float, timeout: float) -> None:
        """只允许一个调用者修改本实例归属和管道句柄。"""
        if (
            not math.isfinite(grace)
            or grace < 0
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            raise ValueError("停止预算必须为有限非负数")
        deadline = time.perf_counter() + timeout
        if self.group._closed:
            return
        if grace > 0 and self.poll() is None:
            self.group.signal(force=False)
            try:
                self.group.wait_empty(min(grace, timeout))
            except TimeoutError:
                pass
        self.scope.stop(
            root_id=self.group_id, timeout=max(0, deadline - time.perf_counter())
        )
        super().wait(timeout=max(0, deadline - time.perf_counter()))
        self.scope.retire(self.group_id)
        self.group.close()
        if self._control is not None:
            self._control.close()

    def communicate(self, input=None, timeout=None):
        """收集目标输出并完成组回收；目标不接受 stdin 数据。"""
        if input is not None:
            raise ValueError("受管目标 stdin 固定为 DEVNULL")
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout 必须为有限非负数")
        deadline = None if timeout is None else time.perf_counter() + timeout
        try:
            # 根退出时先回收仍持有输出管道的后代，再等 EOF；重复 communicate
            # 保留 Popen 已有缓冲与超时后继续读取的语义。
            while True:
                if self.poll() is not None:
                    self.finish()
                remaining = (
                    0.1
                    if deadline is None
                    else min(0.1, max(0, deadline - time.perf_counter()))
                )
                try:
                    return super().communicate(timeout=remaining)
                except subprocess.TimeoutExpired as error:
                    if deadline is not None and time.perf_counter() >= deadline:
                        raise subprocess.TimeoutExpired(
                            self.args, timeout, output=error.output, stderr=error.stderr
                        ) from error
        finally:
            self.stop(grace=0)

    def __exit__(self, *args):
        """上下文退出也不能遗漏已退出根进程的后代。"""
        try:
            self.stop()
        finally:
            for stream in (self.stdout, self.stderr):
                if stream is not None:
                    stream.close()

    def terminate(self) -> None:
        """公共终止入口不能退回 Popen 的单 PID 语义。"""
        self.stop()

    def kill(self) -> None:
        """公共强停入口仍须验证完整组清空。"""
        self.stop(grace=0)

    def finish(self, *, timeout: float = 10) -> None:
        """根命令结束后仍回收全部后代，再关闭组；用于正常完成及崩溃路径。"""
        if self.poll() is None:
            raise RuntimeError("根命令仍运行，不能声明完成")
        self.stop(grace=0, timeout=timeout)
