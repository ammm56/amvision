"""独立 inference daemon 的跨平台本机 mmap 热路径。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from secrets import randbits
from threading import Event, Lock, Thread
from time import monotonic_ns, sleep
from typing import BinaryIO
import json
import mmap
import os
import struct
import zlib

from backend.service.application.error_serialization import serialize_error
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ServiceConfigurationError,
)


_FILE_MAGIC = b"AMVINF1\0"
_FILE_VERSION = 1
# 文件头保持 64 bytes，在原有布局中加入 daemon instance epoch。
_FILE_HEADER = struct.Struct("<8sIIIIQ32x")
# slot header 保持 64 bytes，并把 generation 扩为 uint64，同时记录 request owner token。
_SLOT_HEADER = struct.Struct("<IIIIQQQ24x")
_SLOT_STATE = struct.Struct("<I")
_MAX_UINT64 = 0xFFFFFFFFFFFFFFFF
_ABANDONED_CLAIM_SWEEP_INTERVAL_NS = 1_000_000_000
_RESPONSE_ACK_GRACE_NS = 1_000_000_000
_STATE_FREE = 0
_STATE_REQUEST = 1
_STATE_PROCESSING = 2
_STATE_RESPONSE = 3
_STATE_CANCELLED = 4


class _SlotGuardBusyError(Exception):
    """表示 mailbox 槽位 guard 当前由另一个进程持有。"""


def build_inference_local_mmap_path(*, root_dir: str, service_id: str) -> Path:
    """生成与平台无关的 inference mmap 控制文件路径。"""

    normalized_service_id = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in service_id.strip()
    )
    return (
        Path(root_dir).resolve()
        / "inference-control"
        / f"{normalized_service_id or 'main'}.mmap"
    )


class InferenceLocalMmapClient:
    """通过共享 mmap mailbox 调用独立 inference daemon。"""

    def __init__(
        self,
        *,
        path: str | Path,
        request_timeout_seconds: float,
        poll_interval_seconds: float = 0.001,
    ) -> None:
        """绑定 mmap 文件、请求超时和轮询间隔。"""

        self.path = Path(path).resolve()
        self.request_timeout_seconds = max(0.1, request_timeout_seconds)
        self.poll_interval_seconds = max(0.0005, poll_interval_seconds)
        self._file: BinaryIO | None = None
        self._mmap: mmap.mmap | None = None
        self._slot_count = 0
        self._payload_capacity = 0
        self._slot_stride = 0
        self._open_lock = Lock()

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        """提交小型 JSON 控制载荷并等待同槽位响应。

        图片 bytes 不允许写入 mailbox；Workflow 图片必须继续使用 BufferRef、
        FrameRef 或 ObjectStore ref。
        """

        _reject_inline_image_bytes(payload)
        encoded_request = _encode_payload(payload)
        deadline_ns = monotonic_ns() + int(
            self.request_timeout_seconds * 1_000_000_000
        )
        view = self._require_open()
        server_epoch = _read_server_epoch(view, path=self.path)
        owner_token = _new_u64_token()
        if len(encoded_request) > self._payload_capacity:
            raise InvalidRequestError(
                "inference mmap 请求超过单槽容量",
                details={
                    "request_size": len(encoded_request),
                    "slot_payload_capacity_bytes": self._payload_capacity,
                },
            )
        slot_index, lock_path = self._claim_slot(
            view=view,
            server_epoch=server_epoch,
            owner_token=owner_token,
            deadline_ns=deadline_ns,
        )
        generation: int | None = None
        try:
            generation = self._write_request(
                view=view,
                slot_index=slot_index,
                lock_path=lock_path,
                server_epoch=server_epoch,
                owner_token=owner_token,
                encoded_request=encoded_request,
                deadline_ns=deadline_ns,
            )
            return self._wait_response(
                view=view,
                slot_index=slot_index,
                generation=generation,
                server_epoch=server_epoch,
                owner_token=owner_token,
                deadline_ns=deadline_ns,
            )
        finally:
            self._release_completed_slot(
                view=view,
                slot_index=slot_index,
                generation=generation,
                server_epoch=server_epoch,
                owner_token=owner_token,
                lock_path=lock_path,
            )

    def close(self) -> None:
        """关闭当前进程持有的 mmap view 和文件句柄。"""

        with self._open_lock:
            view = self._mmap
            file = self._file
            self._mmap = None
            self._file = None
        if view is not None:
            view.close()
        if file is not None:
            file.close()

    def _require_open(self) -> mmap.mmap:
        """惰性打开并校验 daemon 创建的 mmap mailbox。"""

        if self._mmap is not None:
            return self._mmap
        with self._open_lock:
            if self._mmap is not None:
                return self._mmap
            try:
                file = self.path.open("r+b", buffering=0)
            except FileNotFoundError as error:
                raise ServiceConfigurationError(
                    "inference daemon mmap 热路径不可达",
                    details={"path": str(self.path)},
                ) from error
            view = mmap.mmap(file.fileno(), length=0, access=mmap.ACCESS_WRITE)
            magic, version, slot_count, payload_capacity, slot_stride, _ = (
                _FILE_HEADER.unpack_from(view, 0)
            )
            if magic != _FILE_MAGIC or version != _FILE_VERSION:
                view.close()
                file.close()
                raise ServiceConfigurationError(
                    "inference daemon mmap 热路径版本不兼容",
                    details={"path": str(self.path), "version": version},
                )
            self._file = file
            self._mmap = view
            self._slot_count = slot_count
            self._payload_capacity = payload_capacity
            self._slot_stride = slot_stride
            return view

    def _claim_slot(
        self,
        *,
        view: mmap.mmap,
        server_epoch: int,
        owner_token: int,
        deadline_ns: int,
    ) -> tuple[int, Path]:
        """用原子创建锁文件的方式申请一个独占 mailbox 槽位。"""

        start_index = (os.getpid() + monotonic_ns()) % self._slot_count
        while monotonic_ns() < deadline_ns:
            for offset in range(self._slot_count):
                slot_index = (start_index + offset) % self._slot_count
                lock_path = _slot_lock_path(self.path, slot_index)
                try:
                    guard_deadline_ns = min(
                        deadline_ns,
                        monotonic_ns()
                        + max(5_000_000, int(self.poll_interval_seconds * 2e9)),
                    )
                    with _acquire_slot_guard(
                        path=self.path,
                        slot_index=slot_index,
                        deadline_ns=guard_deadline_ns,
                        poll_interval_seconds=self.poll_interval_seconds,
                    ):
                        descriptor = os.open(
                            lock_path,
                            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                            0o600,
                        )
                        try:
                            os.write(
                                descriptor,
                                json.dumps(
                                    {
                                        "pid": os.getpid(),
                                        "owner_token": owner_token,
                                        "server_epoch": server_epoch,
                                        "deadline_ns": deadline_ns,
                                    },
                                    separators=(",", ":"),
                                ).encode("utf-8"),
                            )
                        finally:
                            os.close(descriptor)
                        if self._mmap is None:
                            lock_path.unlink(missing_ok=True)
                            raise ServiceConfigurationError(
                                "inference mmap client 尚未打开 mailbox"
                            )
                        if _read_server_epoch(view, path=self.path) != server_epoch:
                            lock_path.unlink(missing_ok=True)
                            raise OperationCancelledError(
                                "inference daemon 在申请 mailbox 槽位时重启",
                                details={"path": str(self.path), "retryable": True},
                            )
                        slot_offset = _FILE_HEADER.size + slot_index * self._slot_stride
                        state = _SLOT_HEADER.unpack_from(view, slot_offset)[0]
                        if state != _STATE_FREE:
                            lock_path.unlink(missing_ok=True)
                            continue
                        return slot_index, lock_path
                except (
                    FileExistsError,
                    PermissionError,
                    _SlotGuardBusyError,
                ):
                    continue
            sleep(self.poll_interval_seconds)
        raise OperationTimeoutError(
            "等待 inference mmap 空闲槽位超时",
            details={"slot_count": self._slot_count, "path": str(self.path)},
        )

    def _write_request(
        self,
        *,
        view: mmap.mmap,
        slot_index: int,
        lock_path: Path,
        server_epoch: int,
        owner_token: int,
        encoded_request: bytes,
        deadline_ns: int,
    ) -> int:
        """先写请求正文，最后发布 REQUEST 状态。"""

        with _acquire_slot_guard(
            path=self.path,
            slot_index=slot_index,
            deadline_ns=deadline_ns,
            poll_interval_seconds=self.poll_interval_seconds,
        ):
            if (
                _read_server_epoch(view, path=self.path) != server_epoch
                or _read_slot_lock_owner(lock_path) != owner_token
            ):
                raise OperationCancelledError(
                    "inference mmap 槽位所有权在请求发布前失效",
                    details={"slot_index": slot_index, "retryable": True},
                )
            slot_offset = _FILE_HEADER.size + slot_index * self._slot_stride
            state, _, _, _, previous_generation, _, _ = _SLOT_HEADER.unpack_from(
                view, slot_offset
            )
            if state != _STATE_FREE:
                raise OperationCancelledError(
                    "inference mmap 槽位在请求发布前不再空闲",
                    details={"slot_index": slot_index, "retryable": True},
                )
            generation = previous_generation % _MAX_UINT64 + 1
            request_offset = slot_offset + _SLOT_HEADER.size
            view[request_offset : request_offset + len(encoded_request)] = (
                encoded_request
            )
            # state 位于 header 首字段，先以 FREE 写完完整 header，最后单独
            # 发布 REQUEST，避免 daemon 读取到半写入 generation/owner/deadline。
            _SLOT_HEADER.pack_into(
                view,
                slot_offset,
                _STATE_FREE,
                len(encoded_request),
                0,
                zlib.crc32(encoded_request),
                generation,
                owner_token,
                deadline_ns,
            )
            _publish_slot_state(
                view,
                slot_offset=slot_offset,
                state=_STATE_REQUEST,
            )
            return generation

    def _wait_response(
        self,
        *,
        view: mmap.mmap,
        slot_index: int,
        generation: int,
        server_epoch: int,
        owner_token: int,
        deadline_ns: int,
    ) -> dict[str, object]:
        """等待 daemon 在同一槽位写回响应。"""

        slot_offset = _FILE_HEADER.size + slot_index * self._slot_stride
        while monotonic_ns() < deadline_ns:
            if _read_server_epoch(view, path=self.path) != server_epoch:
                raise OperationCancelledError(
                    "inference daemon 在请求处理中重启",
                    details={"slot_index": slot_index, "retryable": True},
                )
            (
                state,
                _,
                response_size,
                response_crc,
                current_generation,
                current_owner_token,
                _,
            ) = (
                _SLOT_HEADER.unpack_from(view, slot_offset)
            )
            if (
                current_generation != generation
                or current_owner_token != owner_token
            ):
                # generation 和 owner_token 是两个独立 uint64 字段。正常轮询保持
                # 无锁；只有观察到不一致时才进入现有 slot guard 复核，避免把
                # Windows 跨进程 mmap 的复合 header 交错读取误判为所有权丢失。
                try:
                    with _acquire_slot_guard(
                        path=self.path,
                        slot_index=slot_index,
                        deadline_ns=min(
                            deadline_ns,
                            monotonic_ns()
                            + max(
                                5_000_000,
                                int(self.poll_interval_seconds * 2e9),
                            ),
                        ),
                        poll_interval_seconds=self.poll_interval_seconds,
                    ):
                        (
                            stable_state,
                            _,
                            _,
                            _,
                            stable_generation,
                            stable_owner_token,
                            stable_deadline_ns,
                        ) = _SLOT_HEADER.unpack_from(view, slot_offset)
                        stable_server_epoch = _read_server_epoch(
                            view,
                            path=self.path,
                        )
                        stable_lock_owner = _read_slot_lock_owner(
                            _slot_lock_path(self.path, slot_index)
                        )
                except _SlotGuardBusyError:
                    sleep(self.poll_interval_seconds)
                    continue
                if stable_server_epoch != server_epoch:
                    raise OperationCancelledError(
                        "inference daemon 在请求处理中重启",
                        details={"slot_index": slot_index, "retryable": True},
                    )
                if (
                    stable_generation == generation
                    and stable_owner_token == owner_token
                    and stable_lock_owner == owner_token
                ):
                    continue
                if monotonic_ns() + int(self.poll_interval_seconds * 2e9) >= deadline_ns:
                    break
                raise OperationCancelledError(
                    "inference mmap 槽位所有权在请求处理中失效",
                    details={
                        "slot_index": slot_index,
                        "retryable": True,
                        "expected_generation": generation,
                        "current_generation": stable_generation,
                        "expected_owner_token": owner_token,
                        "current_owner_token": stable_owner_token,
                        "lock_owner_token": stable_lock_owner,
                        "slot_state": stable_state,
                        "request_deadline_ns": deadline_ns,
                        "slot_deadline_ns": stable_deadline_ns,
                        "observed_at_ns": monotonic_ns(),
                    },
                )
            if state == _STATE_RESPONSE:
                if response_size <= 0 or response_size > self._payload_capacity:
                    raise ServiceConfigurationError(
                        "inference mmap 响应长度不合法",
                        details={"slot_index": slot_index, "response_size": response_size},
                    )
                response_offset = (
                    slot_offset + _SLOT_HEADER.size + self._payload_capacity
                )
                encoded_response = bytes(
                    view[response_offset : response_offset + response_size]
                )
                if zlib.crc32(encoded_response) != response_crc:
                    sleep(self.poll_interval_seconds)
                    continue
                return _decode_payload(encoded_response)
            sleep(self.poll_interval_seconds)
        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 1_000_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                (
                    state,
                    _,
                    _,
                    _,
                    current_generation,
                    current_owner_token,
                    _,
                ) = _SLOT_HEADER.unpack_from(view, slot_offset)
                if (
                    _read_server_epoch(view, path=self.path) == server_epoch
                    and current_generation == generation
                    and current_owner_token == owner_token
                    and state in (
                    _STATE_REQUEST,
                    _STATE_PROCESSING,
                    )
                ):
                    _publish_slot_state(
                        view,
                        slot_offset=slot_offset,
                        state=_STATE_CANCELLED,
                    )
        except _SlotGuardBusyError:
            # server 持有 guard 时会重新检查 deadline，并自行发布响应或回收。
            pass
        raise OperationTimeoutError(
            "等待 inference mmap 响应超时",
            details={"slot_index": slot_index, "path": str(self.path)},
        )

    def _release_completed_slot(
        self,
        *,
        view: mmap.mmap,
        slot_index: int,
        generation: int | None,
        server_epoch: int,
        owner_token: int,
        lock_path: Path,
    ) -> None:
        """完成响应后释放槽位；处理中超时的槽位交给 daemon 回收。"""

        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 1_000_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                if (
                    _read_server_epoch(view, path=self.path) != server_epoch
                    or _read_slot_lock_owner(lock_path) != owner_token
                ):
                    return
                if generation is None:
                    lock_path.unlink(missing_ok=True)
                    return
                slot_offset = _FILE_HEADER.size + slot_index * self._slot_stride
                (
                    state,
                    _,
                    _,
                    _,
                    current_generation,
                    current_owner_token,
                    _,
                ) = _SLOT_HEADER.unpack_from(view, slot_offset)
                if (
                    current_generation != generation
                    or current_owner_token != owner_token
                ):
                    return
                if state in (_STATE_RESPONSE, _STATE_REQUEST):
                    _clear_slot(view, slot_offset=slot_offset, generation=generation)
                    lock_path.unlink(missing_ok=True)
        except _SlotGuardBusyError:
            # 请求 deadline 到达后 server 会在同一 guard 下回收，不得无锁清理。
            return


class InferenceLocalMmapServer:
    """在 inference daemon 中消费跨平台 mmap mailbox 请求。"""

    def __init__(
        self,
        *,
        path: str | Path,
        request_handler: Callable[[dict[str, object]], dict[str, object]],
        slot_count: int = 128,
        slot_payload_capacity_bytes: int = 512 * 1024,
        max_concurrent_requests: int = 16,
        poll_interval_seconds: float = 0.001,
    ) -> None:
        """绑定 mailbox 文件、处理器、容量和并发上限。"""

        self.path = Path(path).resolve()
        self.request_handler = request_handler
        self.slot_count = max(1, slot_count)
        self.slot_payload_capacity_bytes = max(64 * 1024, slot_payload_capacity_bytes)
        self.max_concurrent_requests = max(1, max_concurrent_requests)
        self.poll_interval_seconds = max(0.0005, poll_interval_seconds)
        self.slot_stride = _SLOT_HEADER.size + 2 * self.slot_payload_capacity_bytes
        self._file: BinaryIO | None = None
        self._mmap: mmap.mmap | None = None
        self._thread: Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._stop_event = Event()
        self._active_slots: set[int] = set()
        self._active_lock = Lock()
        self._instance_lock_file: BinaryIO | None = None
        self._server_epoch = 0
        self._next_abandoned_claim_sweep_ns = 0

    @property
    def is_running(self) -> bool:
        """返回 mailbox 消费线程是否存活。"""

        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """初始化 mmap 文件并启动有界请求执行器。"""

        if self.is_running:
            return
        instance_lock_file = _acquire_server_instance_lock(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        expected_size = _FILE_HEADER.size + self.slot_count * self.slot_stride
        file: BinaryIO | None = None
        view: mmap.mmap | None = None
        try:
            if self.path.exists():
                file = self.path.open("r+b", buffering=0)
                actual_size = self.path.stat().st_size
                if actual_size != expected_size:
                    raise ServiceConfigurationError(
                        "inference mmap 配置变化需要同时重启 daemon 和 backend-service",
                        details={
                            "path": str(self.path),
                            "actual_size": actual_size,
                            "expected_size": expected_size,
                        },
                    )
            else:
                file = self.path.open("w+b", buffering=0)
                file.truncate(expected_size)
            view = mmap.mmap(file.fileno(), length=0, access=mmap.ACCESS_WRITE)
            server_epoch = _new_u64_token()
            # 初始化期间先发布 epoch=0，client 会将其识别为可重试的 daemon
            # 重启状态；所有旧槽位完成 fencing 后再发布新的有效 epoch。
            _FILE_HEADER.pack_into(
                view,
                0,
                _FILE_MAGIC,
                _FILE_VERSION,
                self.slot_count,
                self.slot_payload_capacity_bytes,
                self.slot_stride,
                0,
            )
            for slot_index in range(self.slot_count):
                with _acquire_slot_guard(
                    path=self.path,
                    slot_index=slot_index,
                    deadline_ns=monotonic_ns() + 1_000_000_000,
                    poll_interval_seconds=self.poll_interval_seconds,
                ):
                    slot_offset = _FILE_HEADER.size + slot_index * self.slot_stride
                    previous_generation = _SLOT_HEADER.unpack_from(view, slot_offset)[4]
                    _clear_slot(
                        view,
                        slot_offset=slot_offset,
                        generation=previous_generation % _MAX_UINT64 + 1,
                    )
                    _slot_lock_path(self.path, slot_index).unlink(missing_ok=True)
            _FILE_HEADER.pack_into(
                view,
                0,
                _FILE_MAGIC,
                _FILE_VERSION,
                self.slot_count,
                self.slot_payload_capacity_bytes,
                self.slot_stride,
                server_epoch,
            )
        except Exception:
            if view is not None:
                view.close()
            if file is not None:
                file.close()
            _release_server_instance_lock(instance_lock_file)
            raise
        self._file = file
        self._mmap = view
        self._server_epoch = server_epoch
        self._instance_lock_file = instance_lock_file
        self._stop_event.clear()
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_requests,
            thread_name_prefix="inference-local-mmap",
        )
        self._thread = Thread(
            target=self._run_loop,
            name="inference-local-mmap-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止消费新请求并关闭 mmap 资源。"""

        if (
            self._instance_lock_file is None
            and self._file is None
            and self._mmap is None
            and self._thread is None
        ):
            return
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        view = self._mmap
        file = self._file
        self._executor = None
        self._thread = None
        self._mmap = None
        self._file = None
        self._server_epoch = 0
        if view is not None:
            view.close()
        if file is not None:
            file.close()
        for slot_index in range(self.slot_count):
            _slot_lock_path(self.path, slot_index).unlink(missing_ok=True)
        instance_lock_file = self._instance_lock_file
        self._instance_lock_file = None
        if instance_lock_file is not None:
            _release_server_instance_lock(instance_lock_file)

    def _run_loop(self) -> None:
        """扫描 REQUEST 槽位并提交到有界线程池。"""

        view = self._mmap
        if view is None:
            return
        while not self._stop_event.is_set():
            dispatched = False
            scan_time_ns = monotonic_ns()
            sweep_abandoned_claims = (
                scan_time_ns >= self._next_abandoned_claim_sweep_ns
            )
            if sweep_abandoned_claims:
                self._next_abandoned_claim_sweep_ns = (
                    scan_time_ns + _ABANDONED_CLAIM_SWEEP_INTERVAL_NS
                )
            for slot_index in range(self.slot_count):
                slot_offset = _FILE_HEADER.size + slot_index * self.slot_stride
                (
                    state,
                    request_size,
                    _,
                    request_crc,
                    generation,
                    owner_token,
                    deadline_ns,
                ) = _SLOT_HEADER.unpack_from(view, slot_offset)
                if state == _STATE_FREE:
                    if sweep_abandoned_claims:
                        self._reclaim_abandoned_claim(slot_index=slot_index)
                    continue
                if state == _STATE_CANCELLED:
                    with self._active_lock:
                        slot_is_active = slot_index in self._active_slots
                    if slot_is_active:
                        continue
                    self._reclaim_inactive_slot(
                        slot_index=slot_index,
                        generation=generation,
                        owner_token=owner_token,
                        allowed_states=(_STATE_CANCELLED,),
                        require_expired=False,
                    )
                    continue
                if state == _STATE_REQUEST and monotonic_ns() >= deadline_ns:
                    self._reclaim_inactive_slot(
                        slot_index=slot_index,
                        generation=generation,
                        owner_token=owner_token,
                        allowed_states=(_STATE_REQUEST,),
                        require_expired=True,
                    )
                    continue
                if (
                    state == _STATE_RESPONSE
                    and monotonic_ns() >= deadline_ns + _RESPONSE_ACK_GRACE_NS
                ):
                    self._reclaim_inactive_slot(
                        slot_index=slot_index,
                        generation=generation,
                        owner_token=owner_token,
                        allowed_states=(_STATE_RESPONSE,),
                        require_expired=True,
                        deadline_grace_ns=_RESPONSE_ACK_GRACE_NS,
                    )
                    continue
                if state != _STATE_REQUEST:
                    continue
                with self._active_lock:
                    if len(self._active_slots) >= self.max_concurrent_requests:
                        break
                    if slot_index in self._active_slots:
                        continue
                try:
                    with _acquire_slot_guard(
                        path=self.path,
                        slot_index=slot_index,
                        deadline_ns=monotonic_ns() + 5_000_000,
                        poll_interval_seconds=self.poll_interval_seconds,
                    ):
                        (
                            guarded_state,
                            guarded_request_size,
                            _,
                            guarded_request_crc,
                            guarded_generation,
                            guarded_owner_token,
                            guarded_deadline_ns,
                        ) = _SLOT_HEADER.unpack_from(view, slot_offset)
                        if (
                            guarded_state != _STATE_REQUEST
                            or guarded_generation != generation
                            or guarded_owner_token != owner_token
                        ):
                            continue
                        if monotonic_ns() >= guarded_deadline_ns:
                            _clear_slot(
                                view,
                                slot_offset=slot_offset,
                                generation=guarded_generation,
                            )
                            _slot_lock_path(self.path, slot_index).unlink(
                                missing_ok=True
                            )
                            continue
                        with self._active_lock:
                            if (
                                len(self._active_slots)
                                >= self.max_concurrent_requests
                                or slot_index in self._active_slots
                            ):
                                continue
                            self._active_slots.add(slot_index)
                        _publish_slot_state(
                            view,
                            slot_offset=slot_offset,
                            state=_STATE_PROCESSING,
                        )
                        request_size = guarded_request_size
                        request_crc = guarded_request_crc
                        owner_token = guarded_owner_token
                        deadline_ns = guarded_deadline_ns
                except _SlotGuardBusyError:
                    continue
                executor = self._executor
                if executor is not None:
                    executor.submit(
                        self._process_slot,
                        slot_index=slot_index,
                        generation=generation,
                        owner_token=owner_token,
                        request_size=request_size,
                        request_crc=request_crc,
                        deadline_ns=deadline_ns,
                    )
                    dispatched = True
            if not dispatched:
                self._stop_event.wait(self.poll_interval_seconds)

    def _reclaim_abandoned_claim(self, *, slot_index: int) -> bool:
        """回收 client 在发布 REQUEST 前崩溃留下的过期锁文件。"""

        lock_path = _slot_lock_path(self.path, slot_index)
        lock_metadata = _read_slot_lock_metadata(lock_path)
        lock_deadline_ns = lock_metadata.get("deadline_ns")
        if (
            not isinstance(lock_deadline_ns, int)
            or monotonic_ns() < lock_deadline_ns
        ):
            return False
        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 5_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                view = self._mmap
                if view is None:
                    return False
                slot_offset = _FILE_HEADER.size + slot_index * self.slot_stride
                if _SLOT_HEADER.unpack_from(view, slot_offset)[0] != _STATE_FREE:
                    return False
                current_metadata = _read_slot_lock_metadata(lock_path)
                if current_metadata != lock_metadata:
                    return False
                lock_path.unlink(missing_ok=True)
                return True
        except _SlotGuardBusyError:
            return False

    def _process_slot(
        self,
        *,
        slot_index: int,
        generation: int,
        owner_token: int,
        request_size: int,
        request_crc: int,
        deadline_ns: int,
    ) -> None:
        """执行一个已领取槽位并写回 JSON 响应。"""

        view = self._mmap
        if view is None:
            return
        slot_offset = _FILE_HEADER.size + slot_index * self.slot_stride
        try:
            request_offset = slot_offset + _SLOT_HEADER.size
            while True:
                encoded_request = bytes(
                    view[request_offset : request_offset + request_size]
                )
                if zlib.crc32(encoded_request) == request_crc:
                    break
                if monotonic_ns() >= deadline_ns:
                    raise InvalidRequestError(
                        "inference mmap 请求在跨进程发布时校验失败"
                    )
                sleep(self.poll_interval_seconds)
            request = _decode_payload(encoded_request)
            try:
                _reject_inline_image_bytes(request)
                result = self.request_handler(request)
                response = {"ok": True, "result": result}
            except Exception as error:  # noqa: BLE001 - mmap 边界需要稳定错误响应
                response = _error_response(error)
            encoded_response = _encode_payload(response)
            if len(encoded_response) > self.slot_payload_capacity_bytes:
                encoded_response = _encode_payload(
                    _error_response(
                        ServiceConfigurationError(
                            "inference mmap 响应超过单槽容量",
                            details={
                                "response_size": len(encoded_response),
                                "slot_payload_capacity_bytes": (
                                    self.slot_payload_capacity_bytes
                                ),
                            },
                        )
                    )
                )
            try:
                with _acquire_slot_guard(
                    path=self.path,
                    slot_index=slot_index,
                    deadline_ns=monotonic_ns() + 1_000_000_000,
                    poll_interval_seconds=self.poll_interval_seconds,
                ):
                    (
                        state,
                        stored_request_size,
                        _,
                        _,
                        stored_generation,
                        stored_owner_token,
                        stored_deadline,
                    ) = _SLOT_HEADER.unpack_from(view, slot_offset)
                    if (
                        stored_generation != generation
                        or stored_owner_token != owner_token
                        or _read_server_epoch(view, path=self.path)
                        != self._server_epoch
                    ):
                        return
                    if (
                        state == _STATE_CANCELLED
                        or monotonic_ns() >= stored_deadline
                    ):
                        _clear_slot(
                            view,
                            slot_offset=slot_offset,
                            generation=generation,
                        )
                        _slot_lock_path(self.path, slot_index).unlink(missing_ok=True)
                        return
                    response_offset = (
                        slot_offset
                        + _SLOT_HEADER.size
                        + self.slot_payload_capacity_bytes
                    )
                    view[response_offset : response_offset + len(encoded_response)] = (
                        encoded_response
                    )
                    # 先保持 PROCESSING 写完响应元数据，再单独发布 RESPONSE。
                    _SLOT_HEADER.pack_into(
                        view,
                        slot_offset,
                        _STATE_PROCESSING,
                        stored_request_size,
                        len(encoded_response),
                        zlib.crc32(encoded_response),
                        stored_generation,
                        stored_owner_token,
                        stored_deadline,
                    )
                    _publish_slot_state(
                        view,
                        slot_offset=slot_offset,
                        state=_STATE_RESPONSE,
                    )
            except _SlotGuardBusyError:
                self._reclaim_finished_slot(
                    slot_index=slot_index,
                    generation=generation,
                    owner_token=owner_token,
                )
        finally:
            with self._active_lock:
                self._active_slots.discard(slot_index)

    def _reclaim_inactive_slot(
        self,
        *,
        slot_index: int,
        generation: int,
        owner_token: int,
        allowed_states: tuple[int, ...],
        require_expired: bool,
        deadline_grace_ns: int = 0,
    ) -> bool:
        """在 guard 下回收未执行槽位，防止与新 client 的 claim 交错。"""

        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 5_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                with self._active_lock:
                    if slot_index in self._active_slots:
                        return False
                view = self._mmap
                if view is None:
                    return False
                slot_offset = _FILE_HEADER.size + slot_index * self.slot_stride
                state, _, _, _, stored_generation, stored_owner_token, deadline_ns = (
                    _SLOT_HEADER.unpack_from(view, slot_offset)
                )
                if (
                    stored_generation != generation
                    or stored_owner_token != owner_token
                    or state not in allowed_states
                ):
                    return False
                if (
                    require_expired
                    and monotonic_ns() < deadline_ns + deadline_grace_ns
                ):
                    return False
                _clear_slot(view, slot_offset=slot_offset, generation=generation)
                _slot_lock_path(self.path, slot_index).unlink(missing_ok=True)
                return True
        except _SlotGuardBusyError:
            return False

    def _reclaim_finished_slot(
        self,
        *,
        slot_index: int,
        generation: int,
        owner_token: int,
    ) -> None:
        """在 handler 结束后按 generation 回收 cancelled/expired 槽位。"""

        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 1_000_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                view = self._mmap
                if view is None:
                    return
                slot_offset = _FILE_HEADER.size + slot_index * self.slot_stride
                state, _, _, _, stored_generation, stored_owner_token, deadline_ns = (
                    _SLOT_HEADER.unpack_from(view, slot_offset)
                )
                if (
                    stored_generation != generation
                    or stored_owner_token != owner_token
                ):
                    return
                if state != _STATE_CANCELLED and monotonic_ns() < deadline_ns:
                    return
                _clear_slot(view, slot_offset=slot_offset, generation=generation)
                _slot_lock_path(self.path, slot_index).unlink(missing_ok=True)
        except _SlotGuardBusyError:
            return


def _slot_lock_path(path: Path, slot_index: int) -> Path:
    """返回一个 mailbox 槽位的跨进程独占锁文件。"""

    return path.with_name(f"{path.name}.slot-{slot_index}.lock")


def _slot_guard_path(path: Path, slot_index: int) -> Path:
    """返回槽位状态切换使用的跨进程 byte-lock 文件。"""

    return path.with_name(f"{path.name}.slot-{slot_index}.guard")


def _server_instance_lock_path(path: Path) -> Path:
    """返回 inference mailbox server 生命周期独占锁文件路径。"""

    return path.with_name(f"{path.name}.server.lock")


def _acquire_server_instance_lock(path: Path) -> BinaryIO:
    """获取 mailbox server 单实例锁，防止两个 daemon 重置同一文件。"""

    lock_path = _server_instance_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+b", buffering=0)
    try:
        if lock_path.stat().st_size == 0:
            lock_file.write(b"\0")
        _lock_guard_file(lock_file)
    except OSError as error:
        lock_file.close()
        raise ServiceConfigurationError(
            "inference mmap mailbox 已由另一个 daemon 实例持有",
            details={"path": str(path)},
        ) from error
    return lock_file


def _release_server_instance_lock(lock_file: BinaryIO) -> None:
    """释放 mailbox server 单实例锁。"""

    try:
        _unlock_guard_file(lock_file)
    finally:
        lock_file.close()


def _new_u64_token() -> int:
    """生成非零 uint64 token，标识 daemon 实例或单次请求 owner。"""

    return randbits(64) or 1


def _read_server_epoch(view: mmap.mmap, *, path: Path) -> int:
    """读取并校验当前 mailbox daemon instance epoch。"""

    magic, version, _, _, _, server_epoch = _FILE_HEADER.unpack_from(view, 0)
    if magic != _FILE_MAGIC or version != _FILE_VERSION or server_epoch == 0:
        raise OperationCancelledError(
            "inference daemon mailbox 当前不可用或正在重启",
            details={"path": str(path), "retryable": True},
        )
    return server_epoch


def _read_slot_lock_owner(lock_path: Path) -> int | None:
    """读取槽位锁文件中的 request owner token；损坏或消失时返回 None。"""

    owner_token = _read_slot_lock_metadata(lock_path).get("owner_token")
    if isinstance(owner_token, int) and owner_token > 0:
        return owner_token
    return None


def _read_slot_lock_metadata(lock_path: Path) -> dict[str, object]:
    """读取槽位锁元数据；文件消失、半写入或损坏时返回空字典。"""

    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError, TypeError):
        return {}
    return {}


@contextmanager
def _acquire_slot_guard(
    *,
    path: Path,
    slot_index: int,
    deadline_ns: int,
    poll_interval_seconds: float,
) -> Iterator[None]:
    """获取 crash-safe 跨进程 byte lock，并在退出时由 OS 释放。"""

    guard_path = _slot_guard_path(path, slot_index)
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    guard_file = guard_path.open("a+b", buffering=0)
    try:
        if guard_path.stat().st_size == 0:
            guard_file.write(b"\0")
        while True:
            try:
                _lock_guard_file(guard_file)
                break
            except OSError as error:
                if monotonic_ns() >= deadline_ns:
                    raise _SlotGuardBusyError from error
                sleep(poll_interval_seconds)
        try:
            yield
        finally:
            _unlock_guard_file(guard_file)
    finally:
        guard_file.close()


def _lock_guard_file(guard_file: BinaryIO) -> None:
    """非阻塞获取一个字节的跨平台进程锁。"""

    guard_file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(guard_file.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(guard_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_guard_file(guard_file: BinaryIO) -> None:
    """释放一个字节的跨平台进程锁。"""

    guard_file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(guard_file.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(guard_file.fileno(), fcntl.LOCK_UN)


def _clear_slot(view: mmap.mmap, *, slot_offset: int, generation: int) -> None:
    """保留 generation 并把槽位恢复为 FREE。"""

    _SLOT_HEADER.pack_into(
        view,
        slot_offset,
        _STATE_FREE,
        0,
        0,
        0,
        generation,
        0,
        0,
    )


def _publish_slot_state(
    view: mmap.mmap,
    *,
    slot_offset: int,
    state: int,
) -> None:
    """在 body 和其余 header 字段稳定后单独发布槽位状态。"""

    _SLOT_STATE.pack_into(view, slot_offset, state)


def _encode_payload(payload: dict[str, object]) -> bytes:
    """把 IPC payload 编码为紧凑 UTF-8 JSON。"""

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(
            "inference mmap payload 不是 JSON 可序列化对象",
            details={"error_message": str(error)},
        ) from error


def _decode_payload(content: bytes) -> dict[str, object]:
    """解码并校验 mmap JSON payload。"""

    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidRequestError("inference mmap payload JSON 不合法") from error
    if not isinstance(payload, dict):
        raise InvalidRequestError("inference mmap payload 必须是对象")
    return payload


def _reject_inline_image_bytes(payload: dict[str, object]) -> None:
    """禁止图片 bytes 或 base64 字段进入 mmap 控制槽位。"""

    request_payload = payload.get("prediction_request")
    if not isinstance(request_payload, dict):
        return
    inline_bytes = request_payload.get("input_image_bytes")
    if inline_bytes not in (None, ""):
        raise InvalidRequestError(
            "inference mmap 热路径禁止传递图片 bytes",
            details={"required_transport": "BufferRef/FrameRef 或 ObjectStore ref"},
        )


def _error_response(error: Exception) -> dict[str, object]:
    """把异常转换为稳定 mmap 错误响应。"""

    serialized = serialize_error(error)
    return {
        "ok": False,
        "error": {
            "code": serialized.get("error_code", "service_error"),
            "message": serialized.get("error_message", str(error)),
            "status_code": serialized.get("status_code", 500),
            "details": serialized.get("details", {}),
        },
    }
