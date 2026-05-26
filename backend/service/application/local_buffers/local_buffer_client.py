"""LocalBufferBroker 客户端协议与事件通道实现。"""

from __future__ import annotations

import mmap
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty
from typing import Any, Protocol
from uuid import uuid4

from dataclasses import dataclass

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.service.application.errors import InvalidRequestError, OperationTimeoutError, ServiceConfigurationError
from backend.service.application.runtime.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)
from backend.service.infrastructure.local_buffers import MmapBufferWriteResult


class LocalBufferReader(Protocol):
    """定义 workflow 节点读取 LocalBufferBroker 引用所需的最小接口。"""

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes:
        """读取普通 BufferRef 对应的字节。

        参数：
        - buffer_ref：普通 mmap buffer 引用。

        返回：
        - bytes：引用范围内的字节内容。
        """

        ...

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes:
        """读取 FrameRef 对应的帧字节。

        参数：
        - frame_ref：ring buffer 帧引用。

        返回：
        - bytes：引用范围内的帧字节内容。
        """

        ...

    def release(self, lease_id: str, *, pool_name: str | None = None) -> None:
        """释放一条 LocalBufferBroker lease。

        参数：
        - lease_id：待释放的 lease id。
        - pool_name：可选的目标 pool 名称。
        """

        ...

    def release_owner(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        owner_id_prefix: str | None = None,
        pool_name: str | None = None,
    ) -> int:
        """释放指定 owner 匹配的全部 LocalBufferBroker lease。

        参数：
        - owner_kind：可选 owner 类型过滤条件。
        - owner_id：可选 owner id 精确匹配条件。
        - owner_id_prefix：可选 owner id 前缀匹配条件。
        - pool_name：可选的目标 pool 名称。

        返回：
        - int：本次释放的 lease 数量。
        """

        ...

    def expire_leases(self, *, pool_name: str | None = None) -> int:
        """触发 broker 回收已经过期的 lease。

        参数：
        - pool_name：可选的目标 pool 名称。

        返回：
        - int：本次回收的 lease 数量。
        """

        ...


@dataclass(frozen=True)
class LocalBufferBrokerEventChannel:
    """描述访问 LocalBufferBroker 状态机所需的事件通道。

    字段：
    - channel_id：当前客户端通道 id；为空表示直接 broker 队列或测试通道。
    - request_queue：客户端发送 broker 控制事件的队列。
    - response_queue：broker 返回事件结果的队列。
    - request_timeout_seconds：单次请求等待响应的最长秒数。
    """

    request_queue: Any
    response_queue: Any
    request_timeout_seconds: float = 5.0
    channel_id: str | None = None


class LocalBufferBrokerClient:
    """通过事件通道访问 LocalBufferBroker。"""

    def __init__(self, channel: LocalBufferBrokerEventChannel) -> None:
        """初始化 broker client。

        参数：
        - channel：broker 事件通道。
        """

        self.channel = channel
        self._mmap_cache = _MmapFileCache()
        self._closed = False
        self._request_count = SafeCounterState()
        self._error_count = SafeCounterState()
        self._last_error: dict[str, object] | None = None

    def get_status(self) -> dict[str, object]:
        """读取 broker 当前状态摘要。"""

        return self._send_request(action="status", payload={})

    def write_bytes(
        self,
        *,
        content: bytes,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        pool_name: str | None = None,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> MmapBufferWriteResult:
        """写入 bytes 并返回可跨进程传递的 BufferRef。

        参数：
        - content：要写入 mmap pool 的字节内容。
        - owner_kind：lease 拥有者类型。
        - owner_id：lease 拥有者实例 id。
        - media_type：内容媒体类型。
        - pool_name：目标 pool 名称；未提供时使用 broker 默认 pool。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - ttl_seconds：可选过期秒数。
        - trace_id：链路追踪 id。

        返回：
        - MmapBufferWriteResult：写入后的 active lease 和 BufferRef。
        """

        lease = self.allocate_buffer(
            size=len(content),
            owner_kind=owner_kind,
            owner_id=owner_id,
            pool_name=pool_name,
            ttl_seconds=ttl_seconds,
            trace_id=trace_id,
        )
        try:
            self.write_lease_bytes(lease=lease, content=content)
            return self.commit_buffer(
                lease=lease,
                media_type=media_type,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
            )
        except Exception:
            self.release(lease.lease_id, pool_name=lease.pool_name)
            raise

    def create_frame_channel(
        self,
        *,
        stream_id: str,
        frame_capacity: int,
        pool_name: str | None = None,
    ) -> dict[str, object]:
        """创建一个 ring buffer frame channel。

        参数：
        - stream_id：连续帧来源 id。
        - frame_capacity：预留帧槽位数量。
        - pool_name：目标 pool 名称；未提供时使用 broker 默认 pool。

        返回：
        - dict[str, object]：channel 状态摘要。
        """

        payload = self._send_request(
            action="create-frame-channel",
            payload={"stream_id": stream_id, "frame_capacity": frame_capacity, "pool_name": pool_name},
        )
        return _require_payload_dict(payload, "channel")

    def write_frame(
        self,
        *,
        stream_id: str,
        content: bytes,
        media_type: str,
        pool_name: str | None = None,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FrameRef:
        """写入一帧并返回可跨进程传递的 FrameRef。

        参数：
        - stream_id：连续帧来源 id。
        - content：当前帧字节内容。
        - media_type：当前帧媒体类型。
        - pool_name：目标 pool 名称；未提供时使用 broker 默认 pool。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - metadata：附加元数据。

        返回：
        - FrameRef：当前帧引用。
        """

        if not isinstance(content, bytes) or not content:
            raise InvalidRequestError("LocalBufferBroker frame 写入内容必须是非空 bytes")
        reservation = self.allocate_frame(
            stream_id=stream_id,
            size=len(content),
            pool_name=pool_name,
        )
        self._mmap_cache.write(
            path=str(reservation["file_path"]),
            offset=int(reservation["offset"]),
            content=content,
            size=int(reservation["size"]),
        )
        return self.commit_frame(
            reservation=reservation,
            media_type=media_type,
            shape=shape,
            dtype=dtype,
            layout=layout,
            pixel_format=pixel_format,
            metadata=metadata,
        )

    def allocate_frame(
        self,
        *,
        stream_id: str,
        size: int,
        pool_name: str | None = None,
    ) -> dict[str, object]:
        """通过 broker 状态机分配 ring frame writing reservation。

        参数：
        - stream_id：连续帧来源 id。
        - size：当前帧有效字节数。
        - pool_name：目标 pool 名称；未提供时使用 broker 默认 pool。

        返回：
        - dict[str, object]：direct mmap 写入所需的 reservation。
        """

        payload = self._send_request(
            action="allocate-frame",
            payload={"stream_id": stream_id, "size": size, "pool_name": pool_name},
        )
        return _require_payload_dict(payload, "reservation")

    def commit_frame(
        self,
        *,
        reservation: dict[str, object],
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FrameRef:
        """把已经 direct mmap 写完的 ring frame 提交为 FrameRef。

        参数：
        - reservation：allocate_frame 返回的写入 reservation。
        - media_type：当前帧媒体类型。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - metadata：附加元数据。

        返回：
        - FrameRef：当前帧引用。
        """

        payload = self._send_request(
            action="commit-frame",
            payload={
                "reservation": dict(reservation),
                "media_type": media_type,
                "shape": tuple(shape),
                "dtype": dtype,
                "layout": layout,
                "pixel_format": pixel_format,
                "metadata": dict(metadata or {}),
            },
        )
        frame_ref_payload = _require_payload_dict(payload, "frame_ref")
        return FrameRef.model_validate(frame_ref_payload)

    def allocate_buffer(
        self,
        *,
        size: int,
        owner_kind: str,
        owner_id: str,
        pool_name: str | None = None,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> BufferLease:
        """通过 broker 状态机分配 writing lease。

        参数：
        - size：本次写入需要的有效字节数。
        - owner_kind：lease 拥有者类型。
        - owner_id：lease 拥有者实例 id。
        - pool_name：目标 pool 名称；未提供时使用 broker 默认 pool。
        - ttl_seconds：可选过期秒数。
        - trace_id：链路追踪 id。

        返回：
        - BufferLease：writing 状态 lease。
        """

        payload = self._send_request(
            action="allocate-buffer",
            payload={
                "pool_name": pool_name,
                "size": size,
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "ttl_seconds": ttl_seconds,
                "trace_id": trace_id,
            },
        )
        lease_payload = _require_payload_dict(payload, "lease")
        return BufferLease.model_validate(lease_payload)

    def write_lease_bytes(self, *, lease: BufferLease, content: bytes) -> None:
        """向 writing lease 对应的 mmap 区域直接写入 bytes。

        参数：
        - lease：broker 分配的 writing lease。
        - content：要写入的内容。
        """

        if not isinstance(content, bytes) or not content:
            raise InvalidRequestError("LocalBufferBroker direct mmap 写入内容必须是非空 bytes")
        if len(content) > lease.size:
            raise InvalidRequestError(
                "LocalBufferBroker direct mmap 写入内容超过 lease 大小",
                details={"lease_id": lease.lease_id, "content_size": len(content), "lease_size": lease.size},
            )
        self._mmap_cache.write(path=lease.file_path, offset=lease.offset, content=content, size=lease.size)

    def commit_buffer(
        self,
        *,
        lease: BufferLease,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
    ) -> MmapBufferWriteResult:
        """把已经 direct mmap 写完的 lease 提交为 BufferRef。

        参数：
        - lease：broker 分配的 writing lease。
        - media_type：内容媒体类型。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。

        返回：
        - MmapBufferWriteResult：提交后的 active lease 和 BufferRef。
        """

        payload = self._send_request(
            action="commit-buffer",
            payload={
                "lease": lease.model_dump(mode="json"),
                "media_type": media_type,
                "shape": tuple(shape),
                "dtype": dtype,
                "layout": layout,
                "pixel_format": pixel_format,
            },
        )
        lease_payload = _require_payload_dict(payload, "lease")
        buffer_ref_payload = _require_payload_dict(payload, "buffer_ref")
        return MmapBufferWriteResult(
            lease=BufferLease.model_validate(lease_payload),
            buffer_ref=BufferRef.model_validate(buffer_ref_payload),
        )

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes:
        """读取普通 BufferRef 对应的字节。

        参数：
        - buffer_ref：普通 mmap buffer 引用。

        返回：
        - bytes：引用范围内的字节内容。
        """

        self._send_request(
            action="validate-buffer-ref",
            payload={"buffer_ref": buffer_ref.model_dump(mode="json")},
        )
        return self._mmap_cache.read(path=buffer_ref.path, offset=buffer_ref.offset, size=buffer_ref.size)

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes:
        """读取 FrameRef 对应的帧字节。

        参数：
        - frame_ref：ring buffer 帧引用。

        返回：
        - bytes：引用范围内的帧字节内容。
        """

        self._send_request(
            action="validate-frame-ref",
            payload={"frame_ref": frame_ref.model_dump(mode="json")},
        )
        return self._mmap_cache.read(path=frame_ref.path, offset=frame_ref.offset, size=frame_ref.size)

    def release(self, lease_id: str, *, pool_name: str | None = None) -> None:
        """释放一条 broker lease。

        参数：
        - lease_id：待释放的 lease id。
        - pool_name：可选的目标 pool 名称。
        """

        self._send_request(action="release", payload={"lease_id": lease_id, "pool_name": pool_name})

    def release_owner(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        owner_id_prefix: str | None = None,
        pool_name: str | None = None,
    ) -> int:
        """释放指定 owner 匹配的全部 broker lease。

        参数：
        - owner_kind：可选 owner 类型过滤条件。
        - owner_id：可选 owner id 精确匹配条件。
        - owner_id_prefix：可选 owner id 前缀匹配条件。
        - pool_name：可选的目标 pool 名称。

        返回：
        - int：本次释放的 lease 数量。
        """

        payload = self._send_request(
            action="release-owner",
            payload={
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "owner_id_prefix": owner_id_prefix,
                "pool_name": pool_name,
            },
        )
        released_count = payload.get("released_count")
        return int(released_count) if isinstance(released_count, int) else 0

    def expire_leases(self, *, pool_name: str | None = None) -> int:
        """触发 broker 回收已经过期的 lease。

        参数：
        - pool_name：可选的目标 pool 名称。

        返回：
        - int：本次回收的 lease 数量。
        """

        payload = self._send_request(action="expire-leases", payload={"pool_name": pool_name})
        expired_count = payload.get("expired_count")
        return int(expired_count) if isinstance(expired_count, int) else 0

    def shutdown(self) -> None:
        """请求 broker 进程优雅退出。"""

        self._send_request(action="shutdown", payload={})

    def close(self) -> None:
        """关闭当前 client 持有的 mmap 文件缓存。"""

        if self._closed:
            return
        self._closed = True
        if self.channel.channel_id is not None:
            try:
                self.channel.request_queue.put(
                    {
                        "request_id": f"close-{uuid4().hex}",
                        "action": "__close-client-channel__",
                        "payload": {"channel_id": self.channel.channel_id},
                    }
                )
            except Exception:
                pass
        self._mmap_cache.close()

    def get_health_summary(self) -> dict[str, object]:
        """返回当前 client 的 broker 调用健康摘要。

        返回：
        - dict[str, object]：包含 channel、请求计数、错误计数和最近错误。
        """

        request_counter_snapshot = snapshot_safe_counter(self._request_count)
        error_counter_snapshot = snapshot_safe_counter(self._error_count)
        return {
            "connected": not self._closed,
            "channel_id": self.channel.channel_id,
            "request_timeout_seconds": self.channel.request_timeout_seconds,
            "request_count": request_counter_snapshot["value"],
            "request_count_rollover_count": request_counter_snapshot["rollover_count"],
            "error_count": error_counter_snapshot["value"],
            "error_count_rollover_count": error_counter_snapshot["rollover_count"],
            "recent_error": dict(self._last_error) if self._last_error is not None else None,
        }

    def _send_request(self, *, action: str, payload: dict[str, object]) -> dict[str, object]:
        """发送一条 broker 事件并解析响应。"""

        request_id = f"broker-{uuid4().hex}"
        increment_safe_counter(self._request_count)
        try:
            self.channel.request_queue.put(
                {"request_id": request_id, "action": action, "payload": dict(payload)}
            )
            response = self.channel.response_queue.get(
                timeout=max(0.1, self.channel.request_timeout_seconds)
            )
        except Empty as exc:
            error = OperationTimeoutError(
                "等待 LocalBufferBroker 响应超时",
                details={"action": action, "timeout_seconds": self.channel.request_timeout_seconds},
            )
            self._record_error(action=action, error=error)
            raise error from exc
        except Exception as exc:
            self._record_error(action=action, error=exc)
            raise
        try:
            payload = _deserialize_response(response, action=action, request_id=request_id)
            self._last_error = None
            return payload
        except Exception as exc:
            self._record_error(action=action, error=exc)
            raise

    def _record_error(self, *, action: str, error: Exception) -> None:
        """记录一次 broker client 调用错误。"""

        details = getattr(error, "details", None)
        increment_safe_counter(self._error_count)
        self._last_error = {
            "action": action,
            "error_type": type(error).__name__,
            "message": getattr(error, "message", str(error) or type(error).__name__),
            "code": getattr(error, "code", "service_configuration_error"),
            "details": dict(details) if isinstance(details, dict) else {},
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }


def _deserialize_response(response: object, *, action: str, request_id: str) -> dict[str, object]:
    """把 broker 响应转换为稳定 payload。"""

    if not isinstance(response, dict):
        raise ServiceConfigurationError("LocalBufferBroker 返回了无效响应", details={"action": action})
    if response.get("request_id") != request_id:
        raise ServiceConfigurationError(
            "LocalBufferBroker 返回了不匹配的事件响应",
            details={"action": action, "request_id": request_id, "response_request_id": response.get("request_id")},
        )
    if response.get("ok") is True:
        payload = response.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}
    error_payload = response.get("error") if isinstance(response.get("error"), dict) else {}
    error_code = str(error_payload.get("code") or "service_configuration_error")
    error_message = str(error_payload.get("message") or "LocalBufferBroker 请求失败")
    error_details = error_payload.get("details") if isinstance(error_payload.get("details"), dict) else {}
    if error_code == "invalid_request":
        raise InvalidRequestError(error_message, details=error_details)
    if error_code == "operation_timeout":
        raise OperationTimeoutError(error_message, details=error_details)
    raise ServiceConfigurationError(error_message, details=error_details)


def _require_payload_dict(payload: dict[str, object], field_name: str) -> dict[str, object]:
    """读取 broker payload 中的对象字段。"""

    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise ServiceConfigurationError(
            "LocalBufferBroker 返回 payload 缺少对象字段",
            details={"field_name": field_name},
        )
    return dict(value)


class _MappedFile:
    """描述客户端进程内缓存的一份 mmap 文件映射。

    字段：
    - file：底层文件句柄。
    - mmap_view：映射视图。
    """

    def __init__(self, path: Path) -> None:
        """打开并映射指定文件。"""

        self.file = path.open("r+b")
        self.mmap_view = mmap.mmap(self.file.fileno(), 0)

    def close(self) -> None:
        """关闭 mmap 视图和文件句柄。"""

        self.mmap_view.close()
        self.file.close()


class _MmapFileCache:
    """缓存当前进程已经打开的 mmap 文件。"""

    def __init__(self) -> None:
        """初始化空 mmap 文件缓存。"""

        self._mapped_files: dict[Path, _MappedFile] = {}

    def write(self, *, path: str, offset: int, content: bytes, size: int) -> None:
        """直接写入 mmap 文件指定区域。

        参数：
        - path：mmap 文件路径。
        - offset：写入起始偏移。
        - content：写入内容。
        - size：lease 允许写入的区域大小。
        """

        mapped_file = self._require_mapped_file(path)
        mapped_file.mmap_view.seek(offset)
        mapped_file.mmap_view.write(content)
        if len(content) < size:
            mapped_file.mmap_view.write(b"\x00" * (size - len(content)))
        mapped_file.mmap_view.flush()

    def read(self, *, path: str, offset: int, size: int) -> bytes:
        """直接读取 mmap 文件指定区域。

        参数：
        - path：mmap 文件路径。
        - offset：读取起始偏移。
        - size：读取字节数。

        返回：
        - bytes：读取到的内容。
        """

        mapped_file = self._require_mapped_file(path)
        mapped_file.mmap_view.seek(offset)
        return mapped_file.mmap_view.read(size)

    def close(self) -> None:
        """关闭全部缓存的 mmap 文件。"""

        for mapped_file in self._mapped_files.values():
            mapped_file.close()
        self._mapped_files.clear()

    def _require_mapped_file(self, path: str) -> _MappedFile:
        """返回指定路径对应的 mmap 文件映射。"""

        file_path = Path(path).resolve()
        mapped_file = self._mapped_files.get(file_path)
        if mapped_file is None:
            mapped_file = _MappedFile(file_path)
            self._mapped_files[file_path] = mapped_file
        return mapped_file