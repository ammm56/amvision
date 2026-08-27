"""与 mmap port 同 envelope/bytes 契约的 multiprocessing.Queue Mailbox adapter。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from queue import Empty
import struct
from threading import Lock
from time import monotonic_ns
from typing import Protocol
from uuid import UUID

from backend.service.application.message_channels.errors import (
    ChannelCancelledError,
    ChannelClosedError,
    ChannelCorruptMessageError,
    ChannelDeadlineExceededError,
    ChannelInvalidMessageError,
    ChannelRestartedError,
    LocalMessageChannelError,
)
from backend.service.application.message_channels.models import MailboxRequestContext
from backend.service.application.message_channels.ports import CancellationSource
from backend.service.infrastructure.ipc.mmap_primitives import (
    crc32_ieee,
    new_nonzero_u64_token,
)


_MAGIC = b"AMVQRP1\0"
_KIND_REQUEST = 1
_KIND_RESPONSE = 2
_KIND_CANCEL = 3
_KIND_CLOSE = 4
_HEADER = struct.Struct("<8sB3x16sQQIII")


class _QueueLike(Protocol):
    """multiprocessing.Queue 与测试 Queue 共用的窄接口。"""

    def put(self, obj: object, block: bool = ..., timeout: float | None = ...) -> None:
        """写入对象。"""

    def get(self, block: bool = ..., timeout: float | None = ...) -> object:
        """读取对象。"""


@dataclass(frozen=True, slots=True)
class _QueueFrame:
    """Queue 内只传输 bytes 的私有 transport frame。"""

    kind: int
    request_id: UUID
    owner_epoch: int
    deadline_ns: int
    error_code: int
    payload: bytes


class QueueMailboxResponseHandle:
    """Queue 已复制响应的幂等 no-op ACK handle。"""

    def __init__(self, wire_bytes: bytes) -> None:
        """保存不可变响应。"""

        self._wire_bytes = bytes(wire_bytes)

    @property
    def wire_bytes(self) -> bytes:
        """返回响应 bytes。"""

        return self._wire_bytes

    def ack(self) -> None:
        """Queue adapter 不持有 server page，ACK 是 no-op。"""

    def close(self) -> None:
        """Queue adapter close 是幂等 no-op ACK。"""


class MultiprocessingQueueMailboxClient:
    """单 endpoint 串行调用的 Queue MailboxClientPort adapter。"""

    def __init__(
        self,
        *,
        request_queue: _QueueLike,
        response_queue: _QueueLike,
        owner_epoch: int,
        poll_interval_seconds: float = 0.001,
    ) -> None:
        """绑定预先由进程父级创建并传递的 Queue handles。"""

        if owner_epoch <= 0:
            raise ValueError("Queue owner_epoch 必须大于 0")
        if poll_interval_seconds <= 0:
            raise ValueError("Queue poll_interval_seconds 必须大于 0")
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.owner_epoch = owner_epoch
        self.poll_interval_seconds = poll_interval_seconds
        self._call_lock = Lock()
        self._closed = False

    def call(
        self,
        *,
        request_id: UUID,
        wire_bytes: bytes,
        deadline_ns: int,
        cancellation: CancellationSource | None = None,
    ) -> QueueMailboxResponseHandle:
        """发送 bytes frame 并等待同 request id 的 response。"""

        with self._call_lock:
            if self._closed:
                raise ChannelClosedError("Queue Mailbox client 已关闭")
            if monotonic_ns() >= deadline_ns:
                raise ChannelDeadlineExceededError("Queue Mailbox deadline 已到期")
            self.request_queue.put(
                _encode_frame(
                    _QueueFrame(
                        kind=_KIND_REQUEST,
                        request_id=request_id,
                        owner_epoch=self.owner_epoch,
                        deadline_ns=deadline_ns,
                        error_code=0,
                        payload=bytes(wire_bytes),
                    )
                )
            )
            while True:
                if cancellation is not None and cancellation.is_cancelled():
                    self._publish_cancel(request_id, deadline_ns)
                    raise ChannelCancelledError("Queue Mailbox client 已取消")
                now_ns = monotonic_ns()
                if now_ns >= deadline_ns:
                    self._publish_cancel(request_id, deadline_ns)
                    raise ChannelDeadlineExceededError("Queue Mailbox response 等待超时")
                try:
                    raw = self.response_queue.get(
                        timeout=min(
                            self.poll_interval_seconds,
                            (deadline_ns - now_ns) / 1e9,
                        )
                    )
                except Empty:
                    continue
                frame = _decode_frame(raw)
                if frame.owner_epoch != self.owner_epoch:
                    raise ChannelRestartedError("Queue Mailbox owner epoch 已变化")
                if frame.kind != _KIND_RESPONSE or frame.request_id != request_id:
                    raise ChannelCorruptMessageError("Queue Mailbox response 路由不匹配")
                if frame.error_code:
                    raise _queue_error(frame.error_code)
                return QueueMailboxResponseHandle(frame.payload)

    def close(self, *, deadline_ns: int) -> None:
        """幂等关闭 client endpoint；不关闭共享 server。"""

        del deadline_ns
        self._closed = True

    def _publish_cancel(self, request_id: UUID, deadline_ns: int) -> None:
        """把 cancel frame 放入同一请求 Queue。"""

        self.request_queue.put(
            _encode_frame(
                _QueueFrame(
                    kind=_KIND_CANCEL,
                    request_id=request_id,
                    owner_epoch=self.owner_epoch,
                    deadline_ns=deadline_ns,
                    error_code=0,
                    payload=b"",
                )
            )
        )


class MultiprocessingQueueMailboxServer:
    """使用 bytes frame 的 Queue MailboxServerPort adapter。"""

    def __init__(
        self,
        *,
        request_queue: _QueueLike,
        response_queue: _QueueLike,
        owner_epoch: int | None = None,
        poll_interval_seconds: float = 0.001,
    ) -> None:
        """初始化单 owner server 与取消/pending registry。"""

        if poll_interval_seconds <= 0:
            raise ValueError("Queue poll_interval_seconds 必须大于 0")
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.owner_epoch = owner_epoch or new_nonzero_u64_token()
        self.poll_interval_seconds = poll_interval_seconds
        self._pending: deque[_QueueFrame] = deque()
        self._cancelled: set[UUID] = set()
        self._completed: set[UUID] = set()
        self._pump_lock = Lock()
        self._closed = False

    def receive(self, *, deadline_ns: int) -> MailboxRequestContext | None:
        """读取 request；cancel/close frame 在 transport 内消费。"""

        while not self._closed:
            frame = self._next_frame(deadline_ns)
            if frame is None:
                return None
            if frame.owner_epoch != self.owner_epoch:
                continue
            if frame.kind == _KIND_CANCEL:
                self._cancelled.add(frame.request_id)
                continue
            if frame.kind == _KIND_CLOSE:
                self._closed = True
                return None
            if frame.kind != _KIND_REQUEST:
                raise ChannelCorruptMessageError("Queue Mailbox request frame kind 不合法")
            if monotonic_ns() >= frame.deadline_ns:
                self._publish_error(frame.request_id, frame.deadline_ns, 1)
                continue
            return MailboxRequestContext(
                request_id=frame.request_id,
                wire_bytes=frame.payload,
                deadline_ns=frame.deadline_ns,
                owner_epoch=self.owner_epoch,
                _cancel_probe=lambda request_id=frame.request_id, deadline_ns=frame.deadline_ns: self._is_cancelled(
                    request_id, deadline_ns
                ),
                _transport_token=frame.request_id,
            )
        return None

    def publish_response(
        self,
        request: MailboxRequestContext,
        *,
        wire_bytes: bytes,
    ) -> None:
        """为 request 最多发布一次 response bytes frame。"""

        if request.owner_epoch != self.owner_epoch:
            raise ChannelRestartedError("Queue Mailbox owner epoch 已变化")
        request_id = request._transport_token
        if not isinstance(request_id, UUID) or request_id != request.request_id:
            raise ChannelInvalidMessageError("Queue MailboxRequestContext 不属于该 adapter")
        if request_id in self._completed:
            raise ChannelInvalidMessageError("Queue Mailbox response 已发布")
        if request.cancelled:
            code = 1 if monotonic_ns() >= request.deadline_ns else 2
            self._publish_error(request_id, request.deadline_ns, code)
            raise _queue_error(code)
        self._completed.add(request_id)
        self.response_queue.put(
            _encode_frame(
                _QueueFrame(
                    kind=_KIND_RESPONSE,
                    request_id=request_id,
                    owner_epoch=self.owner_epoch,
                    deadline_ns=request.deadline_ns,
                    error_code=0,
                    payload=bytes(wire_bytes),
                )
            )
        )

    def close(self, *, deadline_ns: int) -> None:
        """幂等关闭 server endpoint。"""

        del deadline_ns
        self._closed = True

    def _is_cancelled(self, request_id: UUID, deadline_ns: int) -> bool:
        """drain 控制 frame 后检查 cancel/deadline/close。"""

        self._drain_control_frames()
        return (
            self._closed
            or request_id in self._cancelled
            or monotonic_ns() >= deadline_ns
        )

    def _next_frame(self, deadline_ns: int) -> _QueueFrame | None:
        """优先返回 pump 暂存的 request。"""

        with self._pump_lock:
            if self._pending:
                return self._pending.popleft()
            now_ns = monotonic_ns()
            if now_ns >= deadline_ns:
                return None
            try:
                raw = self.request_queue.get(timeout=(deadline_ns - now_ns) / 1e9)
            except Empty:
                return None
            return _decode_frame(raw)

    def _drain_control_frames(self) -> None:
        """非阻塞消费 cancel，把并发 request 保留给下一次 receive。"""

        with self._pump_lock:
            while True:
                try:
                    raw = self.request_queue.get(block=False)
                except Empty:
                    return
                frame = _decode_frame(raw)
                if frame.owner_epoch != self.owner_epoch:
                    continue
                if frame.kind == _KIND_CANCEL:
                    self._cancelled.add(frame.request_id)
                elif frame.kind == _KIND_CLOSE:
                    self._closed = True
                else:
                    self._pending.append(frame)

    def _publish_error(self, request_id: UUID, deadline_ns: int, code: int) -> None:
        """发布稳定 Queue error frame。"""

        if request_id in self._completed:
            return
        self._completed.add(request_id)
        self.response_queue.put(
            _encode_frame(
                _QueueFrame(
                    kind=_KIND_RESPONSE,
                    request_id=request_id,
                    owner_epoch=self.owner_epoch,
                    deadline_ns=deadline_ns,
                    error_code=code,
                    payload=b"",
                )
            )
        )


def _encode_frame(frame: _QueueFrame) -> bytes:
    """把 transport metadata 与 wire payload 编码成单一 bytes 对象。"""

    payload = bytes(frame.payload)
    return _HEADER.pack(
        _MAGIC,
        frame.kind,
        frame.request_id.bytes,
        frame.owner_epoch,
        frame.deadline_ns,
        frame.error_code,
        len(payload),
        crc32_ieee(payload),
    ) + payload


def _decode_frame(raw: object) -> _QueueFrame:
    """拒绝 Python object/dict Queue 消息，只接受完整 bytes frame。"""

    if not isinstance(raw, bytes) or len(raw) < _HEADER.size:
        raise ChannelCorruptMessageError("Queue Mailbox frame 必须是 bytes")
    magic, kind, request_id, epoch, deadline, error, size, checksum = _HEADER.unpack_from(raw)
    payload = raw[_HEADER.size :]
    if magic != _MAGIC or size != len(payload) or crc32_ieee(payload) != checksum:
        raise ChannelCorruptMessageError("Queue Mailbox frame header/CRC 损坏")
    return _QueueFrame(
        kind=kind,
        request_id=UUID(bytes=request_id),
        owner_epoch=epoch,
        deadline_ns=deadline,
        error_code=error,
        payload=payload,
    )


def _queue_error(code: int) -> LocalMessageChannelError:
    """映射 Queue wire error。"""

    if code == 1:
        return ChannelDeadlineExceededError("Queue Mailbox request 超时")
    if code == 2:
        return ChannelCancelledError("Queue Mailbox request 已取消")
    return LocalMessageChannelError(f"Queue Mailbox server error: {code}")
