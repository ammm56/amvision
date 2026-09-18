"""服务状态的后台采集与只读快照；不进入业务调用路径。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
import logging
from threading import Event, Thread
from time import monotonic

LOGGER = logging.getLogger(__name__)


class ServiceStatusMonitor:
    """定期发布序列化快照；HTTP 请求不获取组件锁、不访问数据库或 IPC。"""

    def __init__(
        self,
        collector: Callable[[], list[dict[str, object]]],
        instance_id: str,
        *,
        interval: float = 1.0,
        max_age: float = 5.0,
    ) -> None:
        """设置采集器、启动身份、采集间隔和快照有效期（秒）。"""
        self.collector = collector
        self.instance_id = instance_id
        self.interval = interval
        self.max_age = max_age
        self._stop = Event()
        self._thread: Thread | None = None
        self._ever_ready = False
        self._last_error_type: type[Exception] | None = None
        self._snapshot = (0.0, self._encode([], "starting", "initializing"))
        self._stale = self._encode([], "unavailable", "status_stale")
        self._stopping = self._encode([], "stopping", "service_stopping")

    def _encode(
        self, resources: list[dict[str, object]], state: str, error: str | None = None
    ) -> tuple[int, bytes, bytes]:
        """预序列化公开摘要与完整明细；公开摘要不包含资源 id 或错误原文。"""
        blockers = [item for item in resources if not item["ready"]]
        summary = {
            kind: {
                "expected": len(items),
                "ready": sum(item["ready"] is True for item in items),
            }
            for kind in ("deployments", "runtimes", "triggers")
            for items in ([item for item in resources if item["kind"] == kind],)
        }
        compact_blockers = [
            {"kind": kind, "code": code}
            for kind, code in sorted(
                {(str(item["kind"]), str(item["code"])) for item in blockers}
            )
        ]
        if error:
            compact_blockers.append({"kind": "service", "code": error})
        payload = {
            "ready": state == "ready",
            "state": state,
            "instance_id": self.instance_id,
            "checked_at": datetime.now(UTC).isoformat() if not error else None,
            "summary": summary if not error else None,
            "blockers": compact_blockers,
        }
        return (
            200 if state == "ready" else 503,
            json.dumps(payload, separators=(",", ":")).encode(),
            json.dumps(
                {**payload, "resources": resources}, separators=(",", ":")
            ).encode(),
        )

    def refresh(self) -> None:
        """执行一轮后台采集；失败撤销旧成功结果，不能冒充空资源就绪。"""
        started = monotonic()
        try:
            resources = self.collector()
            ready = all(item["ready"] is True for item in resources)
            state = (
                "ready" if ready else ("degraded" if self._ever_ready else "starting")
            )
            encoded = self._encode(resources, state)
            self._ever_ready |= ready
            self._last_error_type = None
        except Exception as error:  # noqa: BLE001 - 后台监控必须持续工作并撤销成功快照
            if self._last_error_type is not type(error):
                LOGGER.exception("服务状态采集失败")
            self._last_error_type = type(error)
            encoded = self._encode([], "unavailable", "status_collection_failed")
        # 使用开始时间，慢探测不能把旧观测发布为新鲜的成功快照。
        self._snapshot = (started, encoded)

    def response(
        self, *, details: bool = False, stopping: bool = False
    ) -> tuple[int, bytes]:
        """直接读取不可变 bytes；无轮询、等待、深复制或组件查询。"""
        timestamp, encoded = self._snapshot
        if stopping or self._stop.is_set():
            encoded = self._stopping
        elif timestamp and monotonic() - timestamp > self.max_age:
            encoded = self._stale
        return encoded[0], encoded[1 + int(details)]

    def start(self) -> None:
        """启动唯一采集线程；不阻塞 HTTP 启动。"""
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="service-status", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """按固定间隔采集，调用数量不会增加后台采集频率。"""
        while not self._stop.is_set():
            self.refresh()
            self._stop.wait(self.interval)

    def stop(self) -> None:
        """立即撤销就绪并停止采集线程。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.max_age)
