"""跨平台受管进程组；平台机制仅限此适配层，不按进程树快照回收。"""

from __future__ import annotations

import os
import json
import math
from pathlib import Path
import signal
import time

import psutil

from backend.runtime.processes.birth_identity import read_process_birth_identity


class ProcessGroup:
    """持有一次启动的组身份，退出根进程不解除后代归属。"""

    def __init__(self, process):
        """目标必须仍在启动门内；process 提供 pid 和平台进程句柄。"""
        self.pid = process.pid
        self.birth_identity = read_process_birth_identity(self.pid)
        self._job = None
        self._anchor = None
        self._closed = False
        if os.name == "nt":
            from backend.runtime.processes.windows_job import WindowsJob

            self._job = WindowsJob()
            try:
                self._job.assign_handle(int(process._handle))
            except BaseException:
                self._job.close()
                raise
        elif os.getpgid(self.pid) != self.pid:
            raise RuntimeError("目标没有在启动门之前建立独立进程组")
        else:
            path = process.anchor_path
            deadline = time.perf_counter() + 30
            while not path.exists():
                if time.perf_counter() >= deadline or not psutil.pid_exists(self.pid):
                    raise TimeoutError("POSIX 归属守护未就绪")
                time.sleep(0.01)
            self._anchor = json.loads(Path(path).read_text(encoding="utf-8"))
            if not self._anchor_matches():
                raise RuntimeError("POSIX 归属守护身份无效")

    def _anchor_matches(self) -> bool:
        """以活的组内守护身份防止 PGID 复用后误操作。"""
        if not isinstance(self._anchor, dict) or self._anchor.get("pgid") != self.pid:
            raise ValueError("缺少合法的 POSIX 组身份")
        try:
            anchor = psutil.Process(self._anchor["pid"])
            return (
                read_process_birth_identity(anchor.pid) == self._anchor["birth_identity"]
                and anchor.status() != psutil.STATUS_ZOMBIE
                and os.getpgid(anchor.pid) == self.pid
            )
        except (psutil.NoSuchProcess, ProcessLookupError):
            return False

    def members(self) -> tuple[int, ...]:
        """从平台组查询当前成员；权限或查询失败不能解释为已退出。"""
        if self._closed:
            return ()
        if self._job is not None:
            return self._job.members()
        members = []
        for process in psutil.process_iter(["pid", "status"]):
            try:
                if (
                    os.getpgid(process.pid) == self.pid
                    and process.info["status"] != psutil.STATUS_ZOMBIE
                ):
                    members.append(process.pid)
            except ProcessLookupError:
                continue
        return tuple(members)

    def signal(self, *, force: bool) -> None:
        """向整组发送停止；不得因组长已退出而跳过其他成员。"""
        if self._closed:
            return
        if self._job is not None:
            if force:
                self._job.terminate()
            else:
                try:
                    os.kill(self.pid, signal.CTRL_BREAK_EVENT)
                except ProcessLookupError:
                    pass
        else:
            if not self._anchor_matches():
                if self.members():
                    raise RuntimeError(
                        "POSIX 组身份守护已退出且仍有成员，禁止不确定的停止"
                    )
                return
            try:
                os.killpg(self.pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass

    def wait_empty(self, timeout: float) -> None:
        """以高精度单调 deadline 等待全部成员退出。"""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout 必须为有限非负数")
        deadline = time.perf_counter() + timeout
        guardian_stopped = False
        while members := self.members():
            if (
                timeout > 0
                and not guardian_stopped
                and self._anchor is not None
                and members == (self._anchor["pid"],)
            ):
                self.signal(force=True)
                guardian_stopped = True
            if time.perf_counter() >= deadline:
                raise TimeoutError(f"受管进程组未清空：{members}")
            time.sleep(min(0.01, max(0, deadline - time.perf_counter())))

    def finish_guardian(self) -> None:
        """业务成员全部退出后结束唯一的 POSIX 归属守护，不强停业务。"""
        if self._anchor is not None and self.members() == (self._anchor["pid"],):
            self.signal(force=True)
            self.wait_empty(10)

    def close(self) -> None:
        """仅在确认清空后释放归属句柄；失败时保留可重试对象。"""
        self.wait_empty(0)
        if self._job is not None:
            self._job.close()
        self._closed = True

    def release_reference(self) -> None:
        """关闭外部查询句柄，不把引用关闭解释为进程已经退出。"""
        if self._job is not None:
            self._job.close()

    def reference(self) -> dict[str, object]:
        """输出版本化运行时内部引用，不作为业务或模型公开字段。"""
        return {
            "format_id": "amvision.process-group.v2",
            "pid": self.pid,
            "birth_identity": self.birth_identity,
            "backend": "windows-job" if self._job is not None else "posix-group",
            "name": self._job.name if self._job is not None else None,
            "anchor": self._anchor,
        }

    @classmethod
    def open(cls, reference: dict[str, object]) -> ProcessGroup:
        """打开当前平台的既有归属；拒绝旧 PID-only 记录及跨平台误用。"""
        if reference.get("format_id") != "amvision.process-group.v2":
            raise ValueError("缺少当前版本进程组归属")
        expected = "windows-job" if os.name == "nt" else "posix-group"
        if reference.get("backend") != expected:
            raise ValueError("进程组归属与当前系统不匹配")
        result = object.__new__(cls)
        result.pid = int(reference["pid"])
        result.birth_identity = reference["birth_identity"]
        if result.pid <= 0 or not isinstance(result.birth_identity, str) or not result.birth_identity:
            raise ValueError("进程组身份数值无效")
        result._job = None
        result._anchor = reference.get("anchor")
        result._closed = False
        if os.name == "nt":
            from backend.runtime.processes.windows_job import WindowsJob

            name = reference.get("name")
            prefix = "Local\\amvision-process-"
            if (
                not isinstance(name, str)
                or not name.startswith(prefix)
                or len(name) != len(prefix) + 32
                or any(c not in "0123456789abcdef" for c in name[len(prefix) :])
            ):
                raise ValueError("进程组标识无效")
            try:
                result._job = WindowsJob(name=name, open_existing=True)
            except OSError as error:
                if getattr(error, "winerror", None) != 2:
                    raise
                result._closed = True
        else:
            if not result._anchor_matches():
                if result.members():
                    raise RuntimeError("POSIX 组身份守护已退出且仍有成员，拒绝恢复")
                result._closed = True
        return result
