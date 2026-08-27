"""LocalBuffer 固定 arena 的跨独立进程直接访问器。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.service.application.errors import InvalidRequestError
from backend.service.application.local_buffers.broker_settings import (
    LocalBufferBrokerSettings,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    LocalBufferArenaError,
    MmapBufferArenaConfig,
    MmapBufferArenaExternalAccess,
)


class DirectMmapLocalBufferReader:
    """在 deployment worker 内按 descriptor identity 零复制读取图片。

    文件位置只由受信任的 Broker 配置推导。每次读取都先取得 reader guard，
    再校验 arena id、broker epoch、descriptor generation、extent 和状态；
    调用方必须让 acquire view context 覆盖完整消费过程。
    """

    def __init__(
        self,
        settings: LocalBufferBrokerSettings | dict[str, Any],
        *,
        root_dir: str | Path | None = None,
    ) -> None:
        """打开固定 arena 的非 owner 访问器。"""

        self.settings, self.root_dir = _normalize_settings(settings, root_dir=root_dir)
        self._access = MmapBufferArenaExternalAccess(
            _build_config(self.settings, root_dir=self.root_dir)
        )

    def accepts_arena(self, arena_id: str) -> bool:
        """返回 locator 是否属于 backend 主 arena。"""

        return self._access.accepts_arena(arena_id)

    @contextmanager
    def acquire_buffer_ref_view(
        self,
        buffer_ref: BufferRef,
    ) -> Iterator[memoryview]:
        """持有 reader guard 并暴露精确 BufferRef view。"""

        try:
            with self._access.acquire_reader_view(buffer_ref) as view:
                yield view
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error

    @contextmanager
    def acquire_frame_ref_view(self, frame_ref: FrameRef) -> Iterator[memoryview]:
        """持有 reader guard 并暴露精确 FrameRef view。"""

        try:
            with self._access.acquire_reader_view(frame_ref) as view:
                yield view
        except LocalBufferArenaError as error:
            raise InvalidRequestError(str(error)) from error

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes:
        """显式复制 BufferRef；高性能链路使用 acquire_buffer_ref_view。"""

        with self.acquire_buffer_ref_view(buffer_ref) as view:
            return bytes(view)

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes:
        """显式复制 FrameRef；高性能链路使用 acquire_frame_ref_view。"""

        with self.acquire_frame_ref_view(frame_ref) as view:
            return bytes(view)

    def get_health_summary(self) -> dict[str, object]:
        """返回 direct mmap reader 健康摘要。"""

        return {
            "connected": True,
            "transport": "direct-readonly-mmap",
            "arena_id": self.settings.arena_id,
        }

    def close(self) -> None:
        """关闭当前进程的 arena mappings。"""

        self._access.close()


class DirectMmapLocalBufferWriter:
    """在 writer guard 内写入 backend 主 arena 的预分配 lease。"""

    def __init__(
        self,
        settings: LocalBufferBrokerSettings | dict[str, Any],
        *,
        root_dir: str | Path | None = None,
    ) -> None:
        """打开固定 arena 的非 owner 访问器。"""

        self.settings, self.root_dir = _normalize_settings(settings, root_dir=root_dir)
        self._access = MmapBufferArenaExternalAccess(
            _build_config(self.settings, root_dir=self.root_dir)
        )

    def write_lease_bytes(
        self,
        *,
        lease: BufferLease,
        content: bytes | bytearray | memoryview,
    ) -> None:
        """在 guard 与 descriptor 重验后写入结果图片有效前缀。"""

        normalized = memoryview(content)
        try:
            if normalized.nbytes <= 0:
                raise InvalidRequestError("LocalBuffer 结果图片不能为空")
            if lease.state != "writing":
                raise InvalidRequestError(
                    "LocalBuffer 结果图片 lease 不是 writing 状态",
                    details={"lease_id": lease.lease_id, "state": lease.state},
                )
            if normalized.nbytes > lease.content_length:
                raise InvalidRequestError(
                    "LocalBuffer 结果图片超出预分配 extent",
                    details={
                        "lease_id": lease.lease_id,
                        "reserved_content_length": lease.content_length,
                        "content_length": normalized.nbytes,
                    },
                )
            try:
                with self._access.acquire_writer_view(lease) as target:
                    target[: normalized.nbytes] = normalized
            except LocalBufferArenaError as error:
                raise InvalidRequestError(str(error)) from error
        finally:
            normalized.release()

    def accepts_lease(self, lease: BufferLease) -> bool:
        """返回 lease 是否属于 backend 主 arena。"""

        return self._access.accepts_arena(lease.arena_id)

    def close(self) -> None:
        """关闭当前进程的 arena mappings。"""

        self._access.close()


def _normalize_settings(
    settings: LocalBufferBrokerSettings | dict[str, Any],
    *,
    root_dir: str | Path | None,
) -> tuple[LocalBufferBrokerSettings, Path]:
    """拆分 Broker 几何与由 local_memory 提供的受信 root。"""

    if isinstance(settings, LocalBufferBrokerSettings):
        normalized = settings
        raw_root = root_dir
    else:
        payload = dict(settings)
        raw_root = root_dir or payload.pop("buffers_root", None)
        normalized = LocalBufferBrokerSettings.model_validate(payload)
    if raw_root is None or not str(raw_root).strip():
        raise ValueError("Direct LocalBuffer mmap 需要 local_memory root_dir")
    return normalized, Path(raw_root).resolve()


def _build_config(
    settings: LocalBufferBrokerSettings,
    *,
    root_dir: Path,
) -> MmapBufferArenaConfig:
    """把应用配置收敛为唯一固定 arena layout。"""

    return MmapBufferArenaConfig(
        root_dir=root_dir,
        arena_id=settings.arena_id,
        arena_size_bytes=settings.arena_size_bytes,
        min_block_size_bytes=settings.min_block_size_bytes,
        max_allocation_bytes=settings.max_allocation_bytes,
        huge_reserve_bytes=settings.huge_reserve_bytes,
        reader_guard_slots=settings.reader_guard_slots,
        flush_on_write=settings.flush_on_write,
        revocation_grace_seconds=settings.revocation_grace_seconds,
    )
