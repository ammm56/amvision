"""RPC server 独占的固定 overflow page pool。"""

from __future__ import annotations

from threading import Lock

from backend.contracts.ipc.local_message_profiles import RpcChannelProfile
from backend.service.application.message_channels.errors import (
    ChannelCapacityExhaustedError,
    ChannelCorruptMessageError,
)
from backend.service.infrastructure.ipc.local_message.common_layout import (
    NO_PAGE_INDEX,
    PAGE_STATE_FREE,
    PAGE_STATE_PUBLISHED,
    PAGE_STATE_RESERVED,
    RPC_PAGE_HEADER,
    RPC_PAGE_HEADER_SIZE,
    RpcLayout,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    MmapPageChainError,
    crc32_ieee,
    new_nonzero_u64_token,
    publish_u32,
    read_page_chain,
    select_page_indices,
)


class MmapResponsePagePool:
    """在单 RPC owner 内分配、发布、验证并回收 response pages。"""

    def __init__(
        self,
        *,
        view: object,
        profile: RpcChannelProfile,
        layout: RpcLayout,
        owner_epoch: int,
    ) -> None:
        """绑定已校验的可写 mmap view。"""

        self._view = view
        self.profile = profile
        self.layout = layout
        self.owner_epoch = owner_epoch
        self._lock = Lock()

    def reserve_write_publish(
        self,
        *,
        descriptor_index: int,
        descriptor_generation: int,
        payload: bytes,
    ) -> tuple[int, int]:
        """原子保留足够页面，并在完整写入后逐页 publication。"""

        page_capacity = self.profile.overflow_page_capacity_bytes
        page_count = (len(payload) + page_capacity - 1) // page_capacity
        if page_count <= 0:
            return NO_PAGE_INDEX, 0
        if page_count > self.profile.max_overflow_pages_per_response:
            raise ChannelCapacityExhaustedError("响应超过单 response page 上限")
        with self._lock:
            selected = select_page_indices(
                free_page_indices=self._free_page_indices_locked(),
                page_count=page_count,
            )
            if len(selected) != page_count:
                raise ChannelCapacityExhaustedError("RPC response page pool 已满")
            try:
                for ordinal, page_index in enumerate(selected):
                    next_page = (
                        selected[ordinal + 1]
                        if ordinal + 1 < len(selected)
                        else NO_PAGE_INDEX
                    )
                    page_payload = payload[
                        ordinal * page_capacity : (ordinal + 1) * page_capacity
                    ]
                    self._write_reserved_page_locked(
                        page_index=page_index,
                        descriptor_index=descriptor_index,
                        descriptor_generation=descriptor_generation,
                        ordinal=ordinal,
                        next_page_index=next_page,
                        payload=page_payload,
                    )
                for page_index in selected:
                    publish_u32(
                        self._view,
                        offset=self._page_offset(page_index),
                        value=PAGE_STATE_PUBLISHED,
                    )
            except Exception:
                for page_index in selected:
                    self._reset_page_locked(page_index)
                raise
            return selected[0], len(selected)

    def read_published(
        self,
        *,
        first_page_index: int,
        page_count: int,
        descriptor_index: int,
        descriptor_generation: int,
        expected_size: int,
    ) -> bytes:
        """校验 chain identity、长度和逐页 CRC 后复制响应 bytes。"""

        try:
            entries = read_page_chain(
                first_page_index=first_page_index,
                expected_page_count=page_count,
                total_page_count=self.profile.overflow_page_count,
                no_page_index=NO_PAGE_INDEX,
                read_header=self._read_chain_header,
            )
        except MmapPageChainError as error:
            raise ChannelCorruptMessageError(
                f"RPC page-chain 损坏: {error.reason}"
            ) from error
        payload_views: list[memoryview] = []
        view = memoryview(self._view)
        try:
            for page_index, header in entries:
                (
                    state,
                    _flags,
                    actual_descriptor_index,
                    _ordinal,
                    actual_generation,
                    _next_page,
                    payload_size,
                    expected_crc,
                    page_token,
                    page_epoch,
                ) = header
                if state != PAGE_STATE_PUBLISHED:
                    raise ChannelCorruptMessageError("RPC page 尚未完整发布")
                if (
                    actual_descriptor_index != descriptor_index
                    or actual_generation != descriptor_generation
                    or page_epoch != self.owner_epoch
                    or page_token == 0
                ):
                    raise ChannelCorruptMessageError("RPC page identity 不匹配")
                if not 0 < payload_size <= self.profile.overflow_page_capacity_bytes:
                    raise ChannelCorruptMessageError("RPC page payload size 不合法")
                payload_offset = self._page_offset(page_index) + RPC_PAGE_HEADER_SIZE
                content = view[payload_offset : payload_offset + payload_size]
                if crc32_ieee(content) != expected_crc:
                    content.release()
                    raise ChannelCorruptMessageError("RPC page CRC 不匹配")
                payload_views.append(content)
            payload = b"".join(payload_views)
        finally:
            for payload_view in payload_views:
                payload_view.release()
            view.release()
        if len(payload) != expected_size:
            raise ChannelCorruptMessageError("RPC page-chain 总长度不匹配")
        return payload

    def free_for_descriptor(
        self, *, descriptor_index: int, descriptor_generation: int
    ) -> int:
        """按 owner identity 扫描回收页面，不依赖可能损坏的 next pointer。"""

        released = 0
        with self._lock:
            for page_index in range(self.profile.overflow_page_count):
                header = self._read_header(page_index)
                if (
                    header[0] != PAGE_STATE_FREE
                    and header[2] == descriptor_index
                    and header[4] == descriptor_generation
                    and header[9] == self.owner_epoch
                ):
                    self._reset_page_locked(page_index)
                    released += 1
        return released

    def reset_all(self) -> None:
        """owner epoch 初始化时清空所有旧 page metadata。"""

        with self._lock:
            for page_index in range(self.profile.overflow_page_count):
                self._reset_page_locked(page_index)

    def free_page_count(self) -> int:
        """返回当前 FREE page 数。"""

        with self._lock:
            return len(self._free_page_indices_locked())

    def _write_reserved_page_locked(
        self,
        *,
        page_index: int,
        descriptor_index: int,
        descriptor_generation: int,
        ordinal: int,
        next_page_index: int,
        payload: bytes,
    ) -> None:
        """写 RESERVED header 与正文，publication 由调用方最后执行。"""

        page_offset = self._page_offset(page_index)
        RPC_PAGE_HEADER.pack_into(
            self._view,
            page_offset,
            PAGE_STATE_RESERVED,
            0,
            descriptor_index,
            ordinal,
            descriptor_generation,
            next_page_index,
            len(payload),
            crc32_ieee(payload),
            new_nonzero_u64_token(),
            self.owner_epoch,
        )
        payload_offset = page_offset + RPC_PAGE_HEADER_SIZE
        self._view[payload_offset : payload_offset + len(payload)] = payload

    def _free_page_indices_locked(self) -> tuple[int, ...]:
        """读取当前 FREE page index。"""

        return tuple(
            index
            for index in range(self.profile.overflow_page_count)
            if self._read_header(index)[0] == PAGE_STATE_FREE
        )

    def _read_chain_header(
        self, page_index: int
    ) -> tuple[int, tuple[int, ...]]:
        """适配中立 page-chain walker。"""

        header = self._read_header(page_index)
        return header[5], header

    def _read_header(self, page_index: int) -> tuple[int, ...]:
        """读取一个固定 page header。"""

        return RPC_PAGE_HEADER.unpack_from(self._view, self._page_offset(page_index))

    def _reset_page_locked(self, page_index: int) -> None:
        """把 page header 清零为 FREE；正文无需擦除。"""

        page_offset = self._page_offset(page_index)
        self._view[page_offset : page_offset + RPC_PAGE_HEADER_SIZE] = (
            b"\0" * RPC_PAGE_HEADER_SIZE
        )

    def _page_offset(self, page_index: int) -> int:
        """返回 page header 的绝对 mmap offset。"""

        if not 0 <= page_index < self.profile.overflow_page_count:
            raise ChannelCorruptMessageError("RPC page index 越界")
        return self.layout.page_region_offset + page_index * self.layout.page_stride_bytes
