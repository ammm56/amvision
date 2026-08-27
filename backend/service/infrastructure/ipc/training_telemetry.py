"""Training Telemetry 对通用 LocalMessage EventRing 的业务适配。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic, monotonic_ns
from uuid import UUID, uuid4

from backend.contracts.ipc.local_message_profiles import (
    TRAINING_TELEMETRY_EVENT_PROFILE_V1,
    EventRingChannelProfile,
)
from backend.service.application.message_channels.errors import (
    ChannelClosedError,
    ChannelCorruptMessageError,
    ChannelRestartedError,
)
from backend.service.application.message_channels.models import EventCursor
from backend.service.application.models.training.training_telemetry import (
    TrainingTelemetryBroker,
    TrainingTelemetryPoint,
)
from backend.service.application.models.training.training_telemetry_channel import (
    TrainingTelemetryEventPublisher,
    decode_training_telemetry_point,
)
from backend.service.infrastructure.ipc.local_message.event_ring import (
    MmapEventRingPublisher,
    MmapEventRingReader,
)
from backend.service.infrastructure.ipc.local_message.health import EventChannelHealth
from backend.service.infrastructure.ipc.local_message.paths import (
    LocalMessageChannelPaths,
    build_training_telemetry_channel_paths,
)


logger = logging.getLogger(__name__)


class TrainingTelemetryMmapPublisher:
    """为单个 worker session 惰性持有一个通用 EventRing producer。"""

    def __init__(
        self,
        *,
        buffers_root: str | Path,
        min_publish_interval_seconds: float = 0.1,
        profile: EventRingChannelProfile = TRAINING_TELEMETRY_EVENT_PROFILE_V1,
        worker_session_id: UUID | None = None,
    ) -> None:
        """绑定中立 buffers root；profile 只允许代码或测试显式注入。"""

        if min_publish_interval_seconds < 0:
            raise ValueError("min_publish_interval_seconds 不能小于 0")
        self.buffers_root = Path(buffers_root).resolve()
        self.profile = profile
        self.session_id = worker_session_id or uuid4()
        self.paths = build_training_telemetry_channel_paths(
            buffers_root=self.buffers_root,
            worker_session_id=self.session_id,
        )
        self.path = self.paths.mmap_path
        self.min_publish_interval_seconds = min_publish_interval_seconds
        self._publisher: TrainingTelemetryEventPublisher | None = None
        self._lock = RLock()
        self._closed = False

    def start(self) -> None:
        """创建并发布 ready EventRing，使 service 可在首个 batch 前发现 worker。"""

        with self._lock:
            self._require_publisher_locked()

    def publish(self, point: TrainingTelemetryPoint) -> bool:
        """非阻塞发布一个业务遥测点。"""

        with self._lock:
            return self._require_publisher_locked().publish(point)

    def close(self) -> None:
        """幂等发布 producer closed 并释放 owner guard。"""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            publisher = self._publisher
            self._publisher = None
            if publisher is not None:
                publisher.close(deadline_ns=monotonic_ns() + 5_000_000_000)

    def _require_publisher_locked(self) -> TrainingTelemetryEventPublisher:
        """在生命周期锁内返回唯一业务 publisher。"""

        if self._closed:
            raise ChannelClosedError("Training Telemetry publisher 已关闭")
        publisher = self._publisher
        if publisher is None:
            endpoint = MmapEventRingPublisher(
                paths=self.paths,
                profile=self.profile,
                channel_id=self.session_id,
                session_id=self.session_id,
            )
            publisher = TrainingTelemetryEventPublisher(
                publisher=endpoint,
                min_publish_interval_seconds=self.min_publish_interval_seconds,
            )
            self._publisher = publisher
        return publisher


@dataclass(slots=True)
class _ReaderEntry:
    """记录单个 worker EventRing reader 及其 epoch/session cursor。"""

    paths: LocalMessageChannelPaths
    reader: MmapEventRingReader
    cursor: EventCursor | None = None


class TrainingTelemetryMmapReceiver:
    """发现 worker EventRing，并把有效点转发到进程内 replay broker。"""

    def __init__(
        self,
        *,
        buffers_root: str | Path,
        broker: TrainingTelemetryBroker,
        profile: EventRingChannelProfile = TRAINING_TELEMETRY_EVENT_PROFILE_V1,
    ) -> None:
        """绑定中立 buffers root、业务 broker 与冻结 Event profile。"""

        self.buffers_root = Path(buffers_root).resolve()
        self.root_dir = (
            self.buffers_root / "local-message" / "training-telemetry"
        ).resolve()
        self.broker = broker
        self.profile = profile
        self.poll_interval_seconds = profile.poll_interval_seconds
        self.scan_interval_seconds = profile.scan_interval_seconds
        self.replay_limit = profile.slot_count
        self._readers: dict[Path, _ReaderEntry] = {}
        self._pending_cleanup: dict[Path, LocalMessageChannelPaths] = {}
        self._thread: Thread | None = None
        self._stop_event = Event()

    @property
    def is_running(self) -> bool:
        """返回 receiver 线程是否存活。"""

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动固定策略的后台扫描与轮询线程。"""

        if self.is_running:
            return
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run_loop,
            name="training-telemetry-event-ring-receiver",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止 receiver；不删除仍由存活 worker 持有的 EventRing。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(2.0, self.poll_interval_seconds * 4))
        self._thread = None
        for entry in tuple(self._readers.values()):
            entry.reader.close(deadline_ns=monotonic_ns())
        self._readers.clear()
        self._pending_cleanup.clear()

    def poll_once(self) -> int:
        """发现并转发一次，返回进入业务 broker 的有效点数。"""

        self._discover_readers()
        return self._poll_readers()

    def snapshot_health(self) -> tuple[EventChannelHealth, ...]:
        """返回当前 reader 可权威读取的分 Channel Event health。"""

        health: list[EventChannelHealth] = []
        for entry in tuple(self._readers.values()):
            try:
                health.append(entry.reader.health())
            except (OSError, ValueError, ChannelClosedError):
                continue
        return tuple(health)

    def _discover_readers(self) -> None:
        """发现只符合 worker session 命名规则的 EventRing。"""

        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._retry_pending_cleanup()
        for mmap_path in self.root_dir.glob("*.event.mmap"):
            if mmap_path in self._readers or mmap_path in self._pending_cleanup:
                continue
            session_text = mmap_path.name.removesuffix(".event.mmap")
            try:
                session_id = UUID(session_text)
            except ValueError:
                continue
            paths = build_training_telemetry_channel_paths(
                buffers_root=self.buffers_root,
                worker_session_id=session_id,
            )
            if paths.mmap_path != mmap_path.resolve():
                continue
            try:
                reader = MmapEventRingReader(paths=paths, profile=self.profile)
            except (OSError, ValueError, ChannelClosedError):
                continue
            self._readers[mmap_path] = _ReaderEntry(paths=paths, reader=reader)

    def _poll_readers(self) -> int:
        """立即读取所有可用事件，不在单个空 ring 上阻塞。"""

        published_count = 0
        for mmap_path, entry in tuple(self._readers.items()):
            try:
                batch = entry.reader.read(
                    cursor=entry.cursor,
                    deadline_ns=monotonic_ns(),
                    limit=self.replay_limit,
                )
                entry.cursor = batch.next_cursor
            except ChannelRestartedError:
                self._discard_reader(mmap_path=mmap_path, entry=entry)
                continue
            except (OSError, ValueError, ChannelClosedError, ChannelCorruptMessageError):
                remove_files = not self._owner_alive(entry)
                self._discard_reader(
                    mmap_path=mmap_path,
                    entry=entry,
                    remove_files=remove_files,
                )
                continue
            for wire_bytes in batch.events:
                point = decode_training_telemetry_point(wire_bytes)
                if point is None:
                    continue
                try:
                    self.broker.publish(point, force=True)
                except (TypeError, ValueError):
                    continue
                published_count += 1
            owner_alive = self._owner_alive(entry)
            if (batch.producer_closed or not owner_alive) and not owner_alive:
                self._discard_reader(
                    mmap_path=mmap_path,
                    entry=entry,
                    remove_files=True,
                )
        return published_count

    @staticmethod
    def _owner_alive(entry: _ReaderEntry) -> bool:
        """使用 owner guard 判断 producer，而不是依赖 PID 或文件存在性。"""

        try:
            return entry.reader.owner_alive()
        except OSError:
            return False

    def _discard_reader(
        self,
        *,
        mmap_path: Path,
        entry: _ReaderEntry,
        remove_files: bool = False,
    ) -> None:
        """隔离单个 reader，并在 owner 退出后有界清理该 Channel 文件。"""

        self._readers.pop(mmap_path, None)
        try:
            entry.reader.close(deadline_ns=monotonic_ns())
        except (BufferError, OSError):
            logger.warning(
                "关闭训练遥测 EventRing reader 失败：path=%s",
                mmap_path,
                exc_info=True,
            )
            return
        if remove_files and not self._remove_channel_files(entry.paths):
            self._pending_cleanup[mmap_path] = entry.paths

    def _retry_pending_cleanup(self) -> None:
        """重试 Windows 延迟句柄导致的退休 Channel 文件清理。"""

        for mmap_path, paths in tuple(self._pending_cleanup.items()):
            if self._remove_channel_files(paths):
                self._pending_cleanup.pop(mmap_path, None)

    @staticmethod
    def _remove_channel_files(paths: LocalMessageChannelPaths) -> bool:
        """清理单 Channel 的 mmap 与 guard 文件；任一占用时稍后重试。"""

        completed = True
        for path in (paths.mmap_path, paths.owner_lock_path, paths.guard_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                completed = False
        return completed

    def _run_loop(self) -> None:
        """按冻结的 50 ms poll / 100 ms scan 策略持续接收。"""

        next_scan = 0.0
        while not self._stop_event.is_set():
            try:
                now = monotonic()
                if now >= next_scan:
                    self._discover_readers()
                    next_scan = now + self.scan_interval_seconds
                self._poll_readers()
            except Exception:  # noqa: BLE001 - receiver 必须隔离单次异常并自愈
                logger.exception("训练遥测 EventRing receiver 轮询失败，将自动重试")
                next_scan = 0.0
            self._stop_event.wait(self.poll_interval_seconds)


__all__ = [
    "TrainingTelemetryMmapPublisher",
    "TrainingTelemetryMmapReceiver",
]
