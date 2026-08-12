"""训练 worker 到 backend-service 的跨进程 mmap 遥测通道。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4
import hashlib
import json
import logging
import math
import mmap
import os
import struct
import zlib

from backend.service.application.models.training.training_telemetry import (
    TrainingTelemetryBroker,
    TrainingTelemetryPoint,
)


_FILE_MAGIC = b"AMVTRN1\0"
_FILE_VERSION = 1
_FILE_HEADER = struct.Struct("<8sIIII32sQ")
_SLOT_HEADER = struct.Struct("<QQII40x")
_CLOSED_SEQUENCE_FLAG = 1 << 63
_SEQUENCE_VALUE_MASK = _CLOSED_SEQUENCE_FLAG - 1

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrainingTelemetryMmapReadResult:
    """描述一次 ring 读取结果。"""

    session_id: str
    published_sequence: int
    payloads: tuple[dict[str, object], ...]
    gap_detected: bool
    producer_closed: bool


def build_training_telemetry_producer_mmap_path(
    *,
    root_dir: str | Path,
    producer_id: str,
) -> Path:
    """为 worker producer 生成固定长度且不会与其他进程冲突的 mmap 路径。"""

    digest = hashlib.sha256(producer_id.encode("utf-8")).hexdigest()[:24]
    return Path(root_dir).resolve() / f"worker-{os.getpid()}-{digest}.mmap"


class TrainingTelemetryMmapPublisher:
    """把 worker 高频遥测写入单任务有界共享内存 ring。"""

    def __init__(
        self,
        *,
        root_dir: str | Path,
        slot_count: int = 512,
        payload_capacity_bytes: int = 16 * 1024,
        min_publish_interval_seconds: float = 0.1,
    ) -> None:
        """初始化 publisher；每个任务在首次 publish 时惰性创建 mmap。"""

        if slot_count <= 0:
            raise ValueError("slot_count 必须大于 0")
        if payload_capacity_bytes < 1024:
            raise ValueError("payload_capacity_bytes 不能小于 1024")
        if min_publish_interval_seconds < 0:
            raise ValueError("min_publish_interval_seconds 不能小于 0")
        self.root_dir = Path(root_dir).resolve()
        self.slot_count = slot_count
        self.payload_capacity_bytes = payload_capacity_bytes
        self.min_publish_interval_seconds = min_publish_interval_seconds
        self.session_id = uuid4().hex
        self.path = build_training_telemetry_producer_mmap_path(
            root_dir=self.root_dir,
            producer_id=self.session_id,
        )
        self._writer: _TrainingTelemetryMmapWriter | None = None
        self._last_publish_monotonic: dict[str, float] = {}
        self._lock = Lock()

    def publish(self, point: TrainingTelemetryPoint) -> bool:
        """非阻塞写入一个遥测点；节流或载荷过大时返回 False。"""

        now = monotonic()
        with self._lock:
            last = self._last_publish_monotonic.get(point.task_id)
            if (
                last is not None
                and now - last < self.min_publish_interval_seconds
            ):
                return False
            writer = self._require_writer_locked()
            payload = _serialize_transport_point(point)
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded) > self.payload_capacity_bytes:
                return False
            writer.write(encoded)
            self._last_publish_monotonic[point.task_id] = now
        return True

    def start(self) -> None:
        """创建就绪 ring，使 service 可在首个 batch 前发现 worker producer。"""

        with self._lock:
            self._require_writer_locked()

    def close(self) -> None:
        """关闭当前进程持有的全部 mmap view。"""

        with self._lock:
            writer = self._writer
            self._writer = None
            self._last_publish_monotonic.clear()
        if writer is not None:
            writer.close()

    def _require_writer_locked(self) -> _TrainingTelemetryMmapWriter:
        """在已持有 publisher lock 时返回唯一 writer。"""

        writer = self._writer
        if writer is None:
            writer = _TrainingTelemetryMmapWriter(
                path=self.path,
                session_id=self.session_id,
                slot_count=self.slot_count,
                payload_capacity_bytes=self.payload_capacity_bytes,
            )
            self._writer = writer
        return writer


class TrainingTelemetryMmapReader:
    """读取单任务 mmap ring，并用 generation 与 CRC 拒绝 torn payload。"""

    def __init__(self, path: str | Path) -> None:
        """打开并校验一个由 publisher 创建的 mmap 文件。"""

        self.path = Path(path).resolve()
        self._file = self.path.open("r+b", buffering=0)
        self._view = mmap.mmap(self._file.fileno(), length=0, access=mmap.ACCESS_READ)
        (
            magic,
            version,
            self.slot_count,
            self.payload_capacity_bytes,
            self.slot_stride,
            _session,
            _sequence,
        ) = _FILE_HEADER.unpack_from(self._view, 0)
        if magic != _FILE_MAGIC or version != _FILE_VERSION:
            self.close()
            raise ValueError("training telemetry mmap 版本不兼容")
        expected_stride = _SLOT_HEADER.size + self.payload_capacity_bytes
        if self.slot_stride != expected_stride:
            self.close()
            raise ValueError("training telemetry mmap slot_stride 不合法")

    def read_after(
        self,
        *,
        session_id: str | None,
        sequence: int,
        limit: int,
    ) -> TrainingTelemetryMmapReadResult:
        """读取指定 producer cursor 之后的有效载荷。"""

        if limit <= 0:
            raise ValueError("limit 必须大于 0")
        (
            magic,
            version,
            slot_count,
            _capacity,
            _stride,
            raw_session,
            raw_published_sequence,
        ) = _FILE_HEADER.unpack_from(self._view, 0)
        if magic != _FILE_MAGIC or version != _FILE_VERSION:
            raise ValueError("training telemetry mmap header 已变化")
        current_session = raw_session.rstrip(b"\0").decode("ascii")
        producer_closed = bool(raw_published_sequence & _CLOSED_SEQUENCE_FLAG)
        published_sequence = raw_published_sequence & _SEQUENCE_VALUE_MASK
        same_session = session_id == current_session
        oldest_sequence = max(1, published_sequence - slot_count + 1)
        requested_sequence = sequence + 1 if same_session else published_sequence
        start_sequence = max(oldest_sequence, requested_sequence)
        gap_detected = bool(
            same_session
            and sequence > 0
            and sequence < oldest_sequence - 1
        )
        if published_sequence <= 0 or start_sequence > published_sequence:
            return TrainingTelemetryMmapReadResult(
                session_id=current_session,
                published_sequence=published_sequence,
                payloads=(),
                gap_detected=gap_detected,
                producer_closed=producer_closed,
            )
        if published_sequence - start_sequence + 1 > limit:
            start_sequence = published_sequence - limit + 1
            gap_detected = True
        payloads: list[dict[str, object]] = []
        for expected_sequence in range(start_sequence, published_sequence + 1):
            payload = self._read_slot(expected_sequence)
            if payload is None:
                gap_detected = True
                continue
            payloads.append(payload)
        return TrainingTelemetryMmapReadResult(
            session_id=current_session,
            published_sequence=published_sequence,
            payloads=tuple(payloads),
            gap_detected=gap_detected,
            producer_closed=producer_closed,
        )

    def close(self) -> None:
        """关闭 mmap view 与文件。"""

        view = getattr(self, "_view", None)
        file = getattr(self, "_file", None)
        self._view = None
        self._file = None
        if view is not None:
            view.close()
        if file is not None:
            file.close()

    def _read_slot(self, expected_sequence: int) -> dict[str, object] | None:
        """在 header 稳定且 CRC 一致时读取一个 ring slot。"""

        slot_index = (expected_sequence - 1) % self.slot_count
        slot_offset = _FILE_HEADER.size + slot_index * self.slot_stride
        first = _SLOT_HEADER.unpack_from(self._view, slot_offset)
        generation, sequence, payload_size, payload_crc = first
        if generation % 2 != 0 or sequence != expected_sequence:
            return None
        if payload_size <= 0 or payload_size > self.payload_capacity_bytes:
            return None
        payload_offset = slot_offset + _SLOT_HEADER.size
        encoded = bytes(self._view[payload_offset : payload_offset + payload_size])
        second = _SLOT_HEADER.unpack_from(self._view, slot_offset)
        if first != second or zlib.crc32(encoded) != payload_crc:
            return None
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


class TrainingTelemetryMmapReceiver:
    """在 backend-service 中持续把独立 worker ring 转发到进程内 broker。"""

    def __init__(
        self,
        *,
        root_dir: str | Path,
        broker: TrainingTelemetryBroker,
        poll_interval_seconds: float = 0.1,
        scan_interval_seconds: float = 1.0,
        replay_limit: int = 512,
    ) -> None:
        """绑定 mmap 根目录、broker 与有界轮询参数。"""

        self.root_dir = Path(root_dir).resolve()
        self.broker = broker
        self.poll_interval_seconds = max(0.01, poll_interval_seconds)
        self.scan_interval_seconds = max(
            self.poll_interval_seconds,
            scan_interval_seconds,
        )
        self.replay_limit = max(1, replay_limit)
        self._readers: dict[Path, TrainingTelemetryMmapReader] = {}
        self._cursors: dict[Path, tuple[str | None, int]] = {}
        self._pending_cleanup_paths: set[Path] = set()
        self._thread: Thread | None = None
        self._stop_event = Event()

    @property
    def is_running(self) -> bool:
        """返回 receiver 线程是否存活。"""

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动后台轮询线程。"""

        if self.is_running:
            return
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run_loop,
            name="training-telemetry-mmap-receiver",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止轮询并关闭所有 reader。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(2.0, self.poll_interval_seconds * 4))
        self._thread = None
        for reader in tuple(self._readers.values()):
            reader.close()
        self._readers.clear()
        self._cursors.clear()
        self._pending_cleanup_paths.clear()

    def poll_once(self) -> int:
        """扫描并转发一次，返回成功发布的点数。"""

        self._discover_readers()
        return self._poll_readers()

    def _discover_readers(self) -> None:
        """发现尚未打开的 task ring。"""

        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._retry_pending_cleanup()
        for path in self.root_dir.glob("worker-*.mmap"):
            if path in self._readers or path in self._pending_cleanup_paths:
                continue
            try:
                self._readers[path] = TrainingTelemetryMmapReader(path)
                self._cursors[path] = (None, 0)
            except (OSError, ValueError):
                continue

    def _poll_readers(self) -> int:
        """读取所有已打开 ring 并转发有效点。"""

        published_count = 0
        for path, reader in tuple(self._readers.items()):
            session_id, sequence = self._cursors.get(path, (None, 0))
            try:
                result = reader.read_after(
                    session_id=session_id,
                    sequence=sequence,
                    limit=self.replay_limit,
                )
            except (OSError, ValueError):
                self._discard_reader(path=path, reader=reader)
                continue
            self._cursors[path] = (
                result.session_id,
                result.published_sequence,
            )
            for payload in result.payloads:
                point = _deserialize_transport_point(payload)
                if point is None:
                    continue
                try:
                    self.broker.publish(point, force=True)
                except (TypeError, ValueError):
                    continue
                published_count += 1
            if result.producer_closed or not _is_mmap_producer_running(path):
                self._discard_reader(
                    path=path,
                    reader=reader,
                    remove_file=True,
                )
        return published_count

    def _discard_reader(
        self,
        *,
        path: Path,
        reader: TrainingTelemetryMmapReader,
        remove_file: bool = False,
    ) -> None:
        """隔离单个失效 producer；Windows 句柄延迟释放时稍后重试删除。"""

        self._readers.pop(path, None)
        self._cursors.pop(path, None)
        try:
            reader.close()
        except (BufferError, OSError):
            logger.warning(
                "关闭训练遥测 mmap reader 失败，后续扫描会重试：path=%s",
                path,
                exc_info=True,
            )
            return
        if not remove_file:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Windows 在 producer 刚退出时仍可能短暂持有文件句柄。reader 已从
            # 当前集合移除；后续只重试文件清理，禁止再次转发旧 payload。
            self._pending_cleanup_paths.add(path)
            logger.info(
                "训练遥测 mmap 暂时无法清理，后续扫描会重试：path=%s",
                path,
            )

    def _retry_pending_cleanup(self) -> None:
        """重试已退休 producer 文件，且禁止把旧 payload 重放到 broker。"""

        for path in tuple(self._pending_cleanup_paths):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            self._pending_cleanup_paths.discard(path)

    def _run_loop(self) -> None:
        """按低延迟间隔读取已发现文件，并定期发现新任务文件。"""

        next_scan = 0.0
        while not self._stop_event.is_set():
            try:
                now = monotonic()
                if now >= next_scan:
                    self._discover_readers()
                    next_scan = now + self.scan_interval_seconds
                self._poll_readers()
            except Exception:  # noqa: BLE001 - 后台接收线程必须自愈并继续服务
                logger.exception("训练遥测 mmap receiver 轮询失败，将自动重试")
                next_scan = 0.0
            self._stop_event.wait(self.poll_interval_seconds)


class _TrainingTelemetryMmapWriter:
    """管理单个任务的 mmap ring 写句柄。"""

    def __init__(
        self,
        *,
        path: Path,
        session_id: str,
        slot_count: int,
        payload_capacity_bytes: int,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.slot_count = slot_count
        self.payload_capacity_bytes = payload_capacity_bytes
        self.slot_stride = _SLOT_HEADER.size + payload_capacity_bytes
        expected_size = _FILE_HEADER.size + slot_count * self.slot_stride
        if self.path.exists():
            if self.path.stat().st_size != expected_size:
                raise ValueError(
                    "training telemetry mmap 配置变化需要同时重启 service 和 worker"
                )
            self._file = self.path.open("r+b", buffering=0)
        else:
            self._file = self.path.open("w+b", buffering=0)
            self._file.truncate(expected_size)
        self._view = mmap.mmap(self._file.fileno(), length=0, access=mmap.ACCESS_WRITE)
        self._session_bytes = session_id.encode("ascii")[:32].ljust(32, b"\0")
        self._sequence = 0
        _FILE_HEADER.pack_into(
            self._view,
            0,
            _FILE_MAGIC,
            _FILE_VERSION,
            slot_count,
            payload_capacity_bytes,
            self.slot_stride,
            self._session_bytes,
            0,
        )

    def write(self, encoded: bytes) -> None:
        """先写 slot 正文和稳定 header，最后发布全局 sequence。"""

        self._sequence += 1
        slot_index = (self._sequence - 1) % self.slot_count
        slot_offset = _FILE_HEADER.size + slot_index * self.slot_stride
        previous_generation = _SLOT_HEADER.unpack_from(self._view, slot_offset)[0]
        writing_generation = previous_generation + 1
        if writing_generation % 2 == 0:
            writing_generation += 1
        _SLOT_HEADER.pack_into(
            self._view,
            slot_offset,
            writing_generation,
            0,
            0,
            0,
        )
        payload_offset = slot_offset + _SLOT_HEADER.size
        self._view[payload_offset : payload_offset + len(encoded)] = encoded
        _SLOT_HEADER.pack_into(
            self._view,
            slot_offset,
            writing_generation + 1,
            self._sequence,
            len(encoded),
            zlib.crc32(encoded),
        )
        _FILE_HEADER.pack_into(
            self._view,
            0,
            _FILE_MAGIC,
            _FILE_VERSION,
            self.slot_count,
            self.payload_capacity_bytes,
            self.slot_stride,
            self._session_bytes,
            self._sequence,
        )

    def close(self) -> None:
        """关闭单任务 writer。"""

        _FILE_HEADER.pack_into(
            self._view,
            0,
            _FILE_MAGIC,
            _FILE_VERSION,
            self.slot_count,
            self.payload_capacity_bytes,
            self.slot_stride,
            self._session_bytes,
            self._sequence | _CLOSED_SEQUENCE_FLAG,
        )
        self._view.close()
        self._file.close()


def _serialize_transport_point(point: TrainingTelemetryPoint) -> dict[str, object]:
    """构建只含有限标量的 worker transport payload。"""

    return {
        "task_id": point.task_id,
        "attempt_no": point.attempt_no,
        "task_type": point.task_type,
        "model_type": point.model_type,
        "stage": point.stage,
        "granularity": point.granularity,
        "epoch": point.epoch,
        "max_epochs": point.max_epochs,
        "step": point.step,
        "steps_per_epoch": point.steps_per_epoch,
        "global_step": point.global_step,
        "total_steps": point.total_steps,
        "progress_percent": point.progress_percent,
        "learning_rate": point.learning_rate,
        "metrics": {
            str(name): float(value)
            for name, value in point.metrics.items()
            if isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        },
        "input_size": list(point.input_size) if point.input_size is not None else None,
        "runtime": point.runtime,
    }


def _deserialize_transport_point(
    payload: dict[str, object],
) -> TrainingTelemetryPoint | None:
    """严格解析 worker payload；坏 slot 不得终止 receiver。"""

    try:
        granularity = str(payload["granularity"])
        if granularity not in {"batch", "epoch", "validation", "runtime"}:
            return None
        metrics_payload = payload.get("metrics")
        runtime_payload = payload.get("runtime")
        input_size_payload = payload.get("input_size")
        metrics = (
            {
                str(name): float(value)
                for name, value in metrics_payload.items()
                if isinstance(value, int | float) and not isinstance(value, bool)
            }
            if isinstance(metrics_payload, dict)
            else {}
        )
        input_size = (
            (int(input_size_payload[0]), int(input_size_payload[1]))
            if isinstance(input_size_payload, list)
            and len(input_size_payload) == 2
            else None
        )
        return TrainingTelemetryPoint(
            task_id=str(payload["task_id"]),
            attempt_no=int(payload["attempt_no"]),
            task_type=str(payload["task_type"]),
            model_type=str(payload["model_type"]),
            stage=str(payload["stage"]),
            granularity=granularity,  # type: ignore[arg-type]
            epoch=_optional_int(payload.get("epoch")),
            max_epochs=_optional_int(payload.get("max_epochs")),
            step=_optional_int(payload.get("step")),
            steps_per_epoch=_optional_int(payload.get("steps_per_epoch")),
            global_step=_optional_int(payload.get("global_step")),
            total_steps=_optional_int(payload.get("total_steps")),
            progress_percent=_optional_float(payload.get("progress_percent")),
            learning_rate=_optional_float(payload.get("learning_rate")),
            metrics=metrics,
            input_size=input_size,
            runtime=(runtime_payload if isinstance(runtime_payload, dict) else {}),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _optional_int(value: object) -> int | None:
    """解析可选整数且拒绝 bool。"""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("bool 不能作为整数")
    return int(value)


def _optional_float(value: object) -> float | None:
    """解析可选有限浮点数。"""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("bool 不能作为浮点数")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("浮点数必须有限")
    return parsed


def _is_mmap_producer_running(path: Path) -> bool:
    """根据 producer 文件名中的 PID 判断异常退出的 worker。"""

    parts = path.stem.split("-")
    if len(parts) < 3:
        return False
    try:
        process_id = int(parts[1])
    except ValueError:
        return False
    if process_id <= 0:
        return False
    if os.name == "nt":
        return _is_windows_process_running(process_id)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _is_windows_process_running(process_id: int) -> bool:
    """通过只读 Win32 handle 查询进程，绝不向目标进程发送 signal。"""

    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


__all__ = [
    "TrainingTelemetryMmapPublisher",
    "TrainingTelemetryMmapReadResult",
    "TrainingTelemetryMmapReader",
    "TrainingTelemetryMmapReceiver",
    "build_training_telemetry_producer_mmap_path",
]
