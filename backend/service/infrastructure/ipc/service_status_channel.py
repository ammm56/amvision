"""使用既有 EventRing 发布独立状态快照，不占用推理 Mailbox 或 LocalBuffer。"""

from collections.abc import Callable
import json
from threading import Event, Thread
from time import monotonic_ns

from backend.contracts.ipc.local_message_profiles import EventRingChannelProfile
from backend.service.application.message_channels.models import EventPublishResult
from backend.service.infrastructure.ipc.local_message.event_ring import (
    MmapEventRingPublisher,
    MmapEventRingReader,
)
from backend.service.infrastructure.ipc.local_message.paths import (
    build_local_message_channel_paths,
)

# 只保留最近两份完整快照，固定约 512 KiB，不累计历史，不是请求队列。
STATUS_PROFILE = EventRingChannelProfile(
    profile_id="inference-status.v1",
    slot_count=2,
    payload_capacity_bytes=256 * 1024,
    poll_interval_seconds=0.01,
    scan_interval_seconds=1.0,
)


def status_paths(buffers_root: str):
    """与正式 inference owner 同根目录，使用独立状态通道。"""
    return build_local_message_channel_paths(
        buffers_root=buffers_root, channel_name="inference-status", channel_kind="event"
    )


class InferenceStatusPublisher:
    """独立线程每秒发布当前进程状态；执行容量与探测互不竞争。"""

    def __init__(
        self, buffers_root: str, provider: Callable[[], dict[str, object]]
    ) -> None:
        """绑定中立根目录和只读状态提供器。"""
        self.paths = status_paths(buffers_root)
        self.provider = provider
        self._stop = Event()
        self._thread: Thread | None = None
        self._publisher: MmapEventRingPublisher | None = None

    def start(self) -> None:
        """取得独占 owner 后启动发布线程。"""
        self._publisher = MmapEventRingPublisher(
            paths=self.paths, profile=STATUS_PROFILE
        )
        self._thread = Thread(target=self._run, name="inference-status", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """发布完整状态或明确失败；过大时不能继续保留旧成功快照。"""
        try:
            self._publish_loop()
        finally:
            publisher = self._publisher
            if publisher is not None:
                publisher.close(deadline_ns=monotonic_ns())

    def _publish_loop(self) -> None:
        """定期覆盖快照，退出时由线程自己的 finally 关闭 mmap。"""
        while not self._stop.is_set():
            started = monotonic_ns()
            try:
                payload = self.provider()
            except Exception:  # noqa: BLE001 - 状态监控失败不得影响执行器
                payload = {
                    "ready": False,
                    "deployments": [],
                    "code": "status_collection_failed",
                }
            payload["observed_ns"] = started
            publisher = self._publisher
            if publisher is None:
                return
            result = publisher.try_publish(
                json.dumps(payload, separators=(",", ":")).encode()
            )
            if result == EventPublishResult.FULL:
                publisher.try_publish(
                    json.dumps(
                        {
                            "ready": False,
                            "deployments": [],
                            "observed_ns": started,
                            "code": "status_capacity_exceeded",
                        }
                    ).encode()
                )
            self._stop.wait(1.0)

    def stop(self) -> None:
        """关闭发布线程和 owner；reader 会立即拒绝关闭后的状态。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._publisher is not None and (
            self._thread is None or not self._thread.is_alive()
        ):
            self._publisher.close(deadline_ns=monotonic_ns())
            self._publisher = None


def read_inference_status(buffers_root: str) -> dict[str, object]:
    """后台读取最新完整快照；校验 owner、epoch 和时效，不等待新事件。"""
    reader = MmapEventRingReader(
        paths=status_paths(buffers_root), profile=STATUS_PROFILE
    )
    try:
        batch = reader.read(cursor=None, deadline_ns=monotonic_ns(), limit=1)
        if batch.producer_closed or not reader.owner_alive() or not batch.events:
            raise RuntimeError("inference 状态 owner 不可用")
        payload = json.loads(batch.events[-1])
        age = monotonic_ns() - payload["observed_ns"]
        if not 0 <= age <= 5_000_000_000:
            raise RuntimeError("inference 状态快照已过期")
        return payload
    finally:
        reader.close(deadline_ns=monotonic_ns())
