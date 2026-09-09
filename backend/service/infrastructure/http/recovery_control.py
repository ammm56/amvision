"""full Supervisor 专用的进程级排空控制，不经过 HTTP 或数据面。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread
from typing import Callable

from backend.service.infrastructure.http.liveness import ServiceLiveness


class HttpRecoveryControl:
    """只响应绑定本次启动 ID 的两阶段请求，错误后不确认排空。"""

    def __init__(self, directory: Path, liveness: ServiceLiveness,
                 drain: Callable[[], None], shutdown: Callable[[], None], *, inference_owner_lock: str = ""):
        """保存进程身份、独立控制文件和既有生命周期回调。"""
        self.directory, self.liveness = directory, liveness
        self.drain, self.shutdown = drain, shutdown
        self.inference_owner_lock = inference_owner_lock
        self.request = directory / f"{liveness.instance_id}.request.json"
        self.status = directory / f"{liveness.instance_id}.status.json"
        self.stopped = Event()
        self.thread = Thread(target=self._run, name="http-recovery-control", daemon=True)
        self.phase = "ready"

    def start(self) -> None:
        """仅 full 模式创建一个控制线程，正常路径只轮询小文件。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.thread.start()

    def publish(self, phase: str, error: str = "") -> None:
        """原子确认当前启动实例的阶段，禁止用 PID 单独认领。"""
        payload = {"format_id": "amvision.http-recovery.v1", "instance_id": self.liveness.instance_id,
                   "pid": self.liveness.pid, "phase": phase, "error": error[:1024],
                   "inference_owner_lock": self.inference_owner_lock}
        temporary = self.status.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self.status)
        self.phase = phase

    def _run(self) -> None:
        """排空异常保留 failed，不继续关闭 Broker 或请求重启。"""
        while not self.stopped.wait(.2):
            try:
                if not self.request.is_file() or self.request.stat().st_size > 4096:
                    continue
                value = json.loads(self.request.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(value, dict) or value.get("format_id") != "amvision.http-recovery.v1" or (
                value.get("instance_id"), value.get("pid")
            ) != (self.liveness.instance_id, self.liveness.pid):
                continue
            try:
                if value.get("action") == "drain" and self.phase == "ready":
                    self.publish("draining")
                    self.liveness.begin_drain()
                    self.drain()
                    self.publish("drained")
                elif value.get("action") == "shutdown" and self.phase == "drained":
                    self.publish("closing")
                    self.shutdown()
                    return
            except Exception as error:
                self.publish("failed", str(error))
                return

    def close(self) -> None:
        """停止控制轮询；排空未完成时绝不发布 closed。"""
        self.stopped.set()
        self.thread.join(1)
        if self.thread.is_alive():
            raise RuntimeError("HTTP recovery drain is still active")
