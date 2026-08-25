"""独立 inference daemon 的 v1 固定容量 mmap mailbox。"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from pathlib import Path
from math import ceil
from threading import Event, Lock, Thread
from time import monotonic_ns, sleep
from typing import BinaryIO
import json
import logging
import mmap
import os
import struct
import zlib
from collections import deque

from pydantic_core import from_json, to_json

from backend.service.application.error_serialization import serialize_error
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.infrastructure.ipc.mmap_primitives import (
    MmapGuardBusyError,
    MmapOwnerLockBusyError,
    MmapPageChainError,
    acquire_mmap_guard,
    acquire_mmap_owner_lock,
    build_contained_mmap_path,
    crc32_ieee,
    new_nonzero_u64_token,
    publish_u32,
    read_page_chain,
    release_mmap_owner_lock,
    select_page_indices,
)


# 开发阶段的 mailbox 协议固定为 v1。
_FILE_MAGIC = b"AMVMBX1\0"
_FILE_VERSION = 1
# magic/version/descriptor_count/inline_capacity/descriptor_stride/page_count/
# page_capacity/page_stride/max_pages_per_response/server_epoch，共 64 bytes。
_FILE_HEADER = struct.Struct("<8sIIIIIIIIQ16x")
# state/flags/request_size/request_crc/response_size/response_raw_size/response_crc/
# first_page_index/page_count/generation/owner/deadline/server_epoch，共 96 bytes。
_SLOT_HEADER = struct.Struct("<IIIIIIIiIQQQQ28x")
# state/next_page_index/used_size/checksum/descriptor_index/generation/owner，64 bytes。
_PAGE_HEADER = struct.Struct("<IiIIIQQ28x")
_PAGE_STATE = struct.Struct("<I")

_SLOT_STATE_INDEX = 0
_SLOT_FLAGS_INDEX = 1
_SLOT_REQUEST_SIZE_INDEX = 2
_SLOT_REQUEST_CRC_INDEX = 3
_SLOT_RESPONSE_SIZE_INDEX = 4
_SLOT_RESPONSE_RAW_SIZE_INDEX = 5
_SLOT_RESPONSE_CRC_INDEX = 6
_SLOT_FIRST_PAGE_INDEX = 7
_SLOT_PAGE_COUNT_INDEX = 8
_SLOT_GENERATION_INDEX = 9
_SLOT_OWNER_INDEX = 10
_SLOT_DEADLINE_INDEX = 11
_SLOT_SERVER_EPOCH_INDEX = 12

_PAGE_STATE_INDEX = 0
_PAGE_NEXT_INDEX = 1
_PAGE_USED_SIZE_INDEX = 2
_PAGE_CRC_INDEX = 3
_PAGE_DESCRIPTOR_INDEX = 4
_PAGE_GENERATION_INDEX = 5
_PAGE_OWNER_INDEX = 6
_NO_PAGE_INDEX = -1

_MAX_UINT64 = 0xFFFFFFFFFFFFFFFF
_ABANDONED_CLAIM_SWEEP_INTERVAL_NS = 500_000_000
_RESPONSE_ACK_GRACE_NS = 1_000_000_000

_STATE_FREE = 0
_STATE_REQUEST = 1
_STATE_PROCESSING = 2
_STATE_RESPONSE = 3
_STATE_ACKED = 4
_STATE_CANCELLED = 5

_PAGE_FREE = 0
_PAGE_RESERVED = 1
_PAGE_READY = 2

_FLAG_RESPONSE_OVERFLOW = 1 << 0
_FLAG_RESPONSE_ZLIB = 1 << 1
_RESPONSE_METRIC_TASK_TYPES = frozenset(
    {"classification", "detection", "obb", "pose", "segmentation"}
)

LOGGER = logging.getLogger(__name__)


_SlotGuardBusyError = MmapGuardBusyError


class _MmapResponseCapacityExhaustedError(ServiceError):
    """表示固定 mmap 响应容量暂时或永久不足。"""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object],
    ) -> None:
        """初始化稳定容量错误。"""

        super().__init__(
            message,
            code="mmap_response_capacity_exhausted",
            status_code=503,
            details=details,
        )


def build_inference_local_mmap_path(*, root_dir: str, service_id: str) -> Path:
    """生成与平台无关的 inference mmap 文件路径。"""

    normalized_service_id = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in service_id.strip()
    )
    return build_contained_mmap_path(
        root_dir=root_dir,
        relative_path=(
            Path("inference-control") / f"{normalized_service_id or 'main'}.mmap"
        ),
    )


class InferenceLocalMmapClient:
    """通过固定描述符与固定页池调用 inference daemon。"""

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
        self._page_count = 0
        self._page_capacity = 0
        self._page_stride = 0
        self._max_pages_per_response = 0
        self._page_region_offset = 0
        self._open_lock = Lock()

    def request(
        self,
        payload: dict[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """提交 JSON 控制信息；图片内容不得进入 mailbox。"""

        _reject_inline_image_bytes(payload)
        encoded_request = _encode_payload(payload)
        effective_timeout_seconds = max(
            0.1,
            self.request_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds,
        )
        deadline_ns = monotonic_ns() + int(effective_timeout_seconds * 1e9)
        view = self._require_open()
        server_epoch = _read_server_epoch(view, path=self.path)
        owner_token = new_nonzero_u64_token()
        if len(encoded_request) > self._payload_capacity:
            raise InvalidRequestError(
                "inference mmap 请求超过描述符内联容量",
                details={
                    "request_size": len(encoded_request),
                    "inline_capacity_bytes": self._payload_capacity,
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
            self._finish_request(
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
            view, file = self._mmap, self._file
            self._mmap = None
            self._file = None
        if view is not None:
            view.close()
        if file is not None:
            file.close()

    def _require_open(self) -> mmap.mmap:
        """惰性打开并严格校验当前 v1 布局。"""

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
            if len(view) < _FILE_HEADER.size:
                view.close()
                file.close()
                raise ServiceConfigurationError(
                    "inference daemon mmap v1 文件头不完整",
                    details={"path": str(self.path)},
                )
            (
                magic,
                version,
                slot_count,
                payload_capacity,
                slot_stride,
                page_count,
                page_capacity,
                page_stride,
                max_pages_per_response,
                _,
            ) = _FILE_HEADER.unpack_from(view, 0)
            expected_size = (
                _FILE_HEADER.size + slot_count * slot_stride + page_count * page_stride
            )
            valid = (
                magic == _FILE_MAGIC
                and version == _FILE_VERSION
                and slot_count > 0
                and payload_capacity > 0
                and slot_stride == _SLOT_HEADER.size + 2 * payload_capacity
                and page_count > 0
                and page_capacity > 0
                and page_stride == _PAGE_HEADER.size + page_capacity
                and 1 <= max_pages_per_response <= page_count
                and len(view) == expected_size
            )
            if not valid:
                view.close()
                file.close()
                raise ServiceConfigurationError(
                    "inference daemon mmap v1 布局不合法",
                    details={"path": str(self.path), "version": version},
                )
            self._file = file
            self._mmap = view
            self._slot_count = slot_count
            self._payload_capacity = payload_capacity
            self._slot_stride = slot_stride
            self._page_count = page_count
            self._page_capacity = page_capacity
            self._page_stride = page_stride
            self._max_pages_per_response = max_pages_per_response
            self._page_region_offset = _FILE_HEADER.size + slot_count * slot_stride
            return view

    def _claim_slot(
        self,
        *,
        view: mmap.mmap,
        server_epoch: int,
        owner_token: int,
        deadline_ns: int,
    ) -> tuple[int, Path]:
        """用跨进程锁文件申请一个空闲描述符。"""

        start_index = (os.getpid() + monotonic_ns()) % self._slot_count
        while monotonic_ns() < deadline_ns:
            for offset in range(self._slot_count):
                slot_index = (start_index + offset) % self._slot_count
                lock_path = _slot_lock_path(self.path, slot_index)
                try:
                    with _acquire_slot_guard(
                        path=self.path,
                        slot_index=slot_index,
                        deadline_ns=min(deadline_ns, monotonic_ns() + 10_000_000),
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
                        if _read_server_epoch(view, path=self.path) != server_epoch:
                            lock_path.unlink(missing_ok=True)
                            raise OperationCancelledError(
                                "inference daemon 在申请 mailbox 描述符时重启",
                                details={"path": str(self.path), "retryable": True},
                            )
                        slot_offset = _slot_offset(self._slot_stride, slot_index)
                        if (
                            _SLOT_HEADER.unpack_from(view, slot_offset)[0]
                            != _STATE_FREE
                        ):
                            lock_path.unlink(missing_ok=True)
                            continue
                        return slot_index, lock_path
                except (FileExistsError, PermissionError, _SlotGuardBusyError):
                    continue
            sleep(self.poll_interval_seconds)
        raise OperationTimeoutError(
            "等待 inference mmap 空闲描述符超时",
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
        """先写正文和完整 header，最后发布 REQUEST。"""

        with _acquire_slot_guard(
            path=self.path,
            slot_index=slot_index,
            deadline_ns=deadline_ns,
            poll_interval_seconds=self.poll_interval_seconds,
        ):
            if (
                _read_server_epoch(view, path=self.path) != server_epoch
                or not lock_path.exists()
            ):
                raise OperationCancelledError(
                    "inference mmap 描述符所有权在请求发布前失效",
                    details={"slot_index": slot_index, "retryable": True},
                )
            slot_offset = _slot_offset(self._slot_stride, slot_index)
            current = _SLOT_HEADER.unpack_from(view, slot_offset)
            state = current[_SLOT_STATE_INDEX]
            previous_generation = current[_SLOT_GENERATION_INDEX]
            if state != _STATE_FREE:
                raise OperationCancelledError(
                    "inference mmap 描述符在请求发布前不再空闲",
                    details={"slot_index": slot_index, "retryable": True},
                )
            generation = previous_generation % _MAX_UINT64 + 1
            request_offset = slot_offset + _SLOT_HEADER.size
            view[request_offset : request_offset + len(encoded_request)] = (
                encoded_request
            )
            _SLOT_HEADER.pack_into(
                view,
                slot_offset,
                _STATE_FREE,
                0,
                len(encoded_request),
                crc32_ieee(encoded_request),
                0,
                0,
                0,
                _NO_PAGE_INDEX,
                0,
                generation,
                owner_token,
                deadline_ns,
                server_epoch,
            )
            _publish_slot_state(view, slot_offset=slot_offset, state=_STATE_REQUEST)
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
        """等待并读取内联响应或固定溢出页响应。"""

        slot_offset = _slot_offset(self._slot_stride, slot_index)
        while monotonic_ns() < deadline_ns:
            if _read_server_epoch(view, path=self.path) != server_epoch:
                raise OperationCancelledError(
                    "inference daemon 在请求处理中重启",
                    details={"slot_index": slot_index, "retryable": True},
                )
            header = _SLOT_HEADER.unpack_from(view, slot_offset)
            state = header[_SLOT_STATE_INDEX]
            flags = header[_SLOT_FLAGS_INDEX]
            response_size = header[_SLOT_RESPONSE_SIZE_INDEX]
            response_raw_size = header[_SLOT_RESPONSE_RAW_SIZE_INDEX]
            response_crc = header[_SLOT_RESPONSE_CRC_INDEX]
            first_page_index = header[_SLOT_FIRST_PAGE_INDEX]
            page_count = header[_SLOT_PAGE_COUNT_INDEX]
            current_generation = header[_SLOT_GENERATION_INDEX]
            current_owner = header[_SLOT_OWNER_INDEX]
            current_server_epoch = header[_SLOT_SERVER_EPOCH_INDEX]
            if (
                current_generation != generation
                or current_owner != owner_token
                or current_server_epoch != server_epoch
            ):
                if self._ownership_is_current(
                    view=view,
                    slot_index=slot_index,
                    generation=generation,
                    server_epoch=server_epoch,
                    owner_token=owner_token,
                    deadline_ns=deadline_ns,
                ):
                    sleep(self.poll_interval_seconds)
                    continue
                raise OperationCancelledError(
                    "inference mmap 描述符所有权在请求处理中失效",
                    details={"slot_index": slot_index, "retryable": True},
                )
            if state == _STATE_RESPONSE:
                encoded = self._read_encoded_response(
                    view=view,
                    slot_index=slot_index,
                    generation=generation,
                    owner_token=owner_token,
                    flags=flags,
                    response_size=response_size,
                    response_raw_size=response_raw_size,
                    response_crc=response_crc,
                    first_page_index=first_page_index,
                    page_count=page_count,
                )
                if flags & _FLAG_RESPONSE_ZLIB:
                    try:
                        encoded = zlib.decompress(encoded)
                    except zlib.error as error:
                        raise ServiceConfigurationError(
                            "inference mmap 压缩响应不合法",
                            details={"slot_index": slot_index},
                        ) from error
                    if len(encoded) != response_raw_size:
                        raise ServiceConfigurationError(
                            "inference mmap 解压后响应长度不匹配",
                            details={
                                "slot_index": slot_index,
                                "expected_size": response_raw_size,
                                "actual_size": len(encoded),
                            },
                        )
                elif response_raw_size != response_size:
                    raise ServiceConfigurationError(
                        "inference mmap 未压缩响应长度元数据不匹配",
                        details={"slot_index": slot_index},
                    )
                return _decode_payload(encoded)
            if state == _STATE_CANCELLED:
                raise OperationCancelledError(
                    "inference mmap 请求已被 daemon 取消",
                    details={"slot_index": slot_index, "retryable": True},
                )
            sleep(self.poll_interval_seconds)
        self._mark_cancelled(
            view=view,
            slot_index=slot_index,
            generation=generation,
            server_epoch=server_epoch,
            owner_token=owner_token,
        )
        raise OperationTimeoutError(
            "等待 inference mmap 响应超时",
            details={"slot_index": slot_index, "path": str(self.path)},
        )

    def _ownership_is_current(
        self,
        *,
        view: mmap.mmap,
        slot_index: int,
        generation: int,
        server_epoch: int,
        owner_token: int,
        deadline_ns: int,
    ) -> bool:
        """在 guard 内复核复合 header，避免交错读取误判。"""

        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=min(deadline_ns, monotonic_ns() + 10_000_000),
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                header = _SLOT_HEADER.unpack_from(
                    view, _slot_offset(self._slot_stride, slot_index)
                )
                return (
                    _read_server_epoch(view, path=self.path) == server_epoch
                    and header[_SLOT_GENERATION_INDEX] == generation
                    and header[_SLOT_OWNER_INDEX] == owner_token
                    and header[_SLOT_SERVER_EPOCH_INDEX] == server_epoch
                )
        except _SlotGuardBusyError:
            return True

    def _read_encoded_response(
        self,
        *,
        view: mmap.mmap,
        slot_index: int,
        generation: int,
        owner_token: int,
        flags: int,
        response_size: int,
        response_raw_size: int,
        response_crc: int,
        first_page_index: int,
        page_count: int,
    ) -> bytes:
        """读取响应并校验 descriptor、page chain 和 CRC。"""

        if response_size <= 0:
            raise ServiceConfigurationError(
                "inference mmap 响应长度不合法",
                details={"slot_index": slot_index, "response_size": response_size},
            )
        if not flags & _FLAG_RESPONSE_OVERFLOW:
            if (
                response_size > self._payload_capacity
                or first_page_index != _NO_PAGE_INDEX
                or page_count != 0
            ):
                raise ServiceConfigurationError(
                    "inference mmap 内联响应元数据不合法",
                    details={"slot_index": slot_index, "response_size": response_size},
                )
            response_offset = (
                _slot_offset(self._slot_stride, slot_index)
                + _SLOT_HEADER.size
                + self._payload_capacity
            )
            encoded = bytes(view[response_offset : response_offset + response_size])
        else:
            expected_page_count = (
                response_size + self._page_capacity - 1
            ) // self._page_capacity
            if (
                page_count != expected_page_count
                or page_count <= 0
                or page_count > self._max_pages_per_response
                or first_page_index < 0
                or first_page_index >= self._page_count
            ):
                raise ServiceConfigurationError(
                    "inference mmap 溢出链 descriptor 元数据不合法",
                    details={
                        "slot_index": slot_index,
                        "first_page_index": first_page_index,
                        "page_count": page_count,
                        "expected_page_count": expected_page_count,
                    },
                )
            pages: list[bytes] = []

            def _read_page_header(page_index: int) -> tuple[int, tuple[object, ...]]:
                page_offset = self._page_region_offset + page_index * self._page_stride
                header = _PAGE_HEADER.unpack_from(view, page_offset)
                return int(header[_PAGE_NEXT_INDEX]), header

            try:
                page_entries = read_page_chain(
                    first_page_index=first_page_index,
                    expected_page_count=page_count,
                    total_page_count=self._page_count,
                    no_page_index=_NO_PAGE_INDEX,
                    read_header=_read_page_header,
                )
            except MmapPageChainError as error:
                message = {
                    "cycle_or_out_of_bounds": "inference mmap 溢出 page chain 循环或越界",
                    "ended_early": "inference mmap 溢出 page chain 提前结束",
                    "too_long": "inference mmap 溢出 page chain 长度超出 descriptor",
                }[error.reason]
                raise ServiceConfigurationError(
                    message,
                    details={
                        "slot_index": slot_index,
                        "page_index": error.page_index,
                    },
                ) from error
            for page_index, raw_header in page_entries:
                (
                    state,
                    _next_page_index,
                    used_size,
                    checksum,
                    current_slot,
                    current_generation,
                    current_owner,
                ) = raw_header
                if (
                    state != _PAGE_READY
                    or current_slot != slot_index
                    or current_generation != generation
                    or current_owner != owner_token
                ):
                    raise ServiceConfigurationError(
                        "inference mmap 溢出页身份不合法",
                        details={"slot_index": slot_index, "page_index": page_index},
                    )
                if used_size <= 0 or used_size > self._page_capacity:
                    raise ServiceConfigurationError(
                        "inference mmap 溢出页长度不合法",
                        details={"slot_index": slot_index, "page_index": page_index},
                    )
                page_offset = self._page_region_offset + page_index * self._page_stride
                body_offset = page_offset + _PAGE_HEADER.size
                content = bytes(view[body_offset : body_offset + used_size])
                if crc32_ieee(content) != checksum:
                    raise ServiceConfigurationError(
                        "inference mmap 溢出页校验失败",
                        details={"slot_index": slot_index, "page_index": page_index},
                    )
                pages.append(content)
            encoded = b"".join(pages)
            if len(encoded) != response_size:
                raise ServiceConfigurationError(
                    "inference mmap 溢出响应长度不匹配",
                    details={"slot_index": slot_index, "response_size": response_size},
                )
        max_raw_size = max(
            self._payload_capacity,
            self._max_pages_per_response * self._page_capacity,
        )
        if response_raw_size <= 0 or response_raw_size > max_raw_size:
            raise ServiceConfigurationError(
                "inference mmap 原始响应长度不合法",
                details={
                    "slot_index": slot_index,
                    "response_raw_size": response_raw_size,
                    "max_raw_size": max_raw_size,
                },
            )
        if crc32_ieee(encoded) != response_crc:
            raise ServiceConfigurationError(
                "inference mmap 响应校验失败",
                details={"slot_index": slot_index},
            )
        return encoded

    def _mark_cancelled(
        self,
        *,
        view: mmap.mmap,
        slot_index: int,
        generation: int,
        server_epoch: int,
        owner_token: int,
    ) -> None:
        """超时后只发布 CANCELLED，实际资源由 daemon 回收。"""

        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 1_000_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                slot_offset = _slot_offset(self._slot_stride, slot_index)
                header = _SLOT_HEADER.unpack_from(view, slot_offset)
                if (
                    _read_server_epoch(view, path=self.path) == server_epoch
                    and header[_SLOT_GENERATION_INDEX] == generation
                    and header[_SLOT_OWNER_INDEX] == owner_token
                    and header[_SLOT_SERVER_EPOCH_INDEX] == server_epoch
                    and header[_SLOT_STATE_INDEX] in (_STATE_REQUEST, _STATE_PROCESSING)
                ):
                    _publish_slot_state(
                        view,
                        slot_offset=slot_offset,
                        state=_STATE_CANCELLED,
                    )
        except _SlotGuardBusyError:
            pass

    def _finish_request(
        self,
        *,
        view: mmap.mmap,
        slot_index: int,
        generation: int | None,
        server_epoch: int,
        owner_token: int,
        lock_path: Path,
    ) -> None:
        """观察到完整响应后 ACK；其他在途状态发布取消。"""

        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 1_000_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                slot_offset = _slot_offset(self._slot_stride, slot_index)
                header = _SLOT_HEADER.unpack_from(view, slot_offset)
                try:
                    current_server_epoch = _read_server_epoch(view, path=self.path)
                except OperationCancelledError:
                    return
                if current_server_epoch != server_epoch:
                    return
                if generation is None and header[_SLOT_STATE_INDEX] == _STATE_FREE:
                    lock_path.unlink(missing_ok=True)
                    return
                if (
                    header[_SLOT_GENERATION_INDEX] != generation
                    or header[_SLOT_OWNER_INDEX] != owner_token
                    or header[_SLOT_SERVER_EPOCH_INDEX] != server_epoch
                ):
                    return
                if header[_SLOT_STATE_INDEX] == _STATE_RESPONSE:
                    _publish_slot_state(
                        view,
                        slot_offset=slot_offset,
                        state=_STATE_ACKED,
                    )
                elif header[_SLOT_STATE_INDEX] in (
                    _STATE_REQUEST,
                    _STATE_PROCESSING,
                ):
                    _publish_slot_state(
                        view,
                        slot_offset=slot_offset,
                        state=_STATE_CANCELLED,
                    )
        except _SlotGuardBusyError:
            return


class InferenceLocalMmapServer:
    """消费 v1 mmap mailbox，并独占管理固定溢出页池。"""

    def __init__(
        self,
        *,
        path: str | Path,
        request_handler: Callable[[dict[str, object]], dict[str, object]],
        slot_count: int = 128,
        slot_payload_capacity_bytes: int = 512 * 1024,
        overflow_page_count: int = 256,
        overflow_page_capacity_bytes: int = 512 * 1024,
        max_overflow_pages_per_response: int = 64,
        compression_threshold_bytes: int = 256 * 1024,
        max_concurrent_requests: int = 16,
        poll_interval_seconds: float = 0.001,
    ) -> None:
        """绑定固定描述符、固定页池及并发上限。"""

        if slot_count <= 0:
            raise ServiceConfigurationError("inference mmap descriptor 数量必须大于 0")
        if slot_payload_capacity_bytes < 64 * 1024:
            raise ServiceConfigurationError("inference mmap 内联容量不能小于 64 KiB")
        if overflow_page_count <= 0:
            raise ServiceConfigurationError("inference mmap 溢出页数量必须大于 0")
        if overflow_page_capacity_bytes < 64 * 1024:
            raise ServiceConfigurationError("inference mmap 溢出页容量不能小于 64 KiB")
        if not 1 <= max_overflow_pages_per_response <= overflow_page_count:
            raise ServiceConfigurationError(
                "inference mmap 单响应页数必须位于固定页池范围内"
            )
        if compression_threshold_bytes < 0:
            raise ServiceConfigurationError("inference mmap 压缩阈值不能小于 0")
        if max_concurrent_requests <= 0:
            raise ServiceConfigurationError("inference mmap 执行并发必须大于 0")
        if poll_interval_seconds <= 0:
            raise ServiceConfigurationError("inference mmap 轮询间隔必须大于 0")
        self.path = Path(path).resolve()
        self.request_handler = request_handler
        self.slot_count = slot_count
        self.slot_payload_capacity_bytes = slot_payload_capacity_bytes
        self.overflow_page_count = overflow_page_count
        self.overflow_page_capacity_bytes = overflow_page_capacity_bytes
        self.max_overflow_pages_per_response = max_overflow_pages_per_response
        self.compression_threshold_bytes = compression_threshold_bytes
        self.max_concurrent_requests = max_concurrent_requests
        self.poll_interval_seconds = max(0.0005, poll_interval_seconds)
        self.slot_stride = _SLOT_HEADER.size + 2 * self.slot_payload_capacity_bytes
        self.page_stride = _PAGE_HEADER.size + self.overflow_page_capacity_bytes
        self.page_region_offset = _FILE_HEADER.size + self.slot_count * self.slot_stride
        self._file: BinaryIO | None = None
        self._mmap: mmap.mmap | None = None
        self._thread: Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._stop_event = Event()
        self._active_slots: set[int] = set()
        self._active_lock = Lock()
        self._page_pool_lock = Lock()
        self._page_allocations: dict[tuple[int, int, int], tuple[int, ...]] = {}
        self._instance_lock_file: BinaryIO | None = None
        self._server_epoch = 0
        self._next_abandoned_claim_sweep_ns = 0
        self._page_pool_high_watermark = 0
        self._metrics_lock = Lock()
        self._response_count = 0
        self._overflow_response_count = 0
        self._compressed_response_count = 0
        self._capacity_exhausted_count = 0
        self._response_raw_sizes: deque[int] = deque(maxlen=4096)
        self._response_raw_sizes_by_task: dict[str, deque[int]] = {}

    @property
    def is_running(self) -> bool:
        """返回 mailbox 消费线程是否存活。"""

        return self._thread is not None and self._thread.is_alive()

    def get_health_summary(self) -> dict[str, object]:
        """返回固定描述符和页池的即时容量，不修改任何所有权。"""

        view = self._mmap
        if view is None:
            return {
                "ready": False,
                "protocol_version": _FILE_VERSION,
            }
        descriptor_states: dict[str, int] = {
            "free": 0,
            "request": 0,
            "processing": 0,
            "response": 0,
            "acked": 0,
            "cancelled": 0,
        }
        state_names = {
            _STATE_FREE: "free",
            _STATE_REQUEST: "request",
            _STATE_PROCESSING: "processing",
            _STATE_RESPONSE: "response",
            _STATE_ACKED: "acked",
            _STATE_CANCELLED: "cancelled",
        }
        for slot_index in range(self.slot_count):
            state = _SLOT_HEADER.unpack_from(
                view,
                _slot_offset(self.slot_stride, slot_index),
            )[0]
            name = state_names.get(state)
            if name is not None:
                descriptor_states[name] += 1
        with self._active_lock:
            active_execution_count = len(self._active_slots)
        with self._page_pool_lock:
            free_page_count = sum(
                _PAGE_HEADER.unpack_from(view, self._page_offset(index))[0]
                == _PAGE_FREE
                for index in range(self.overflow_page_count)
            )
            page_pool_high_watermark = self._page_pool_high_watermark
        with self._metrics_lock:
            response_metrics = {
                "response_count": self._response_count,
                "overflow_response_count": self._overflow_response_count,
                "compressed_response_count": self._compressed_response_count,
                "capacity_exhausted_count": self._capacity_exhausted_count,
                "raw_size_bytes": _build_size_summary(self._response_raw_sizes),
                "raw_size_bytes_by_task_type": {
                    task_type: _build_size_summary(sizes)
                    for task_type, sizes in sorted(
                        self._response_raw_sizes_by_task.items()
                    )
                },
            }
        return {
            "ready": self.is_running,
            "protocol_version": _FILE_VERSION,
            "server_epoch": self._server_epoch,
            "descriptor_count": self.slot_count,
            "descriptor_states": descriptor_states,
            "active_execution_count": active_execution_count,
            "max_concurrent_requests": self.max_concurrent_requests,
            "inline_capacity_bytes": self.slot_payload_capacity_bytes,
            "overflow_page_count": self.overflow_page_count,
            "overflow_page_capacity_bytes": self.overflow_page_capacity_bytes,
            "free_overflow_page_count": free_page_count,
            "used_overflow_page_count": self.overflow_page_count - free_page_count,
            "overflow_page_high_watermark": page_pool_high_watermark,
            "max_overflow_pages_per_response": self.max_overflow_pages_per_response,
            "max_response_bytes": (
                max(
                    self.slot_payload_capacity_bytes,
                    self.max_overflow_pages_per_response
                    * self.overflow_page_capacity_bytes,
                )
            ),
            "response_metrics": response_metrics,
        }

    def start(self) -> None:
        """按当前配置初始化 v1 mailbox 文件。"""

        if self.is_running:
            return
        instance_lock_file = _acquire_server_instance_lock(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        expected_size = (
            self.page_region_offset + self.overflow_page_count * self.page_stride
        )
        file: BinaryIO | None = None
        view: mmap.mmap | None = None
        try:
            file = self.path.open("r+b" if self.path.exists() else "w+b", buffering=0)
            if self.path.stat().st_size != expected_size:
                file.truncate(expected_size)
            view = mmap.mmap(file.fileno(), length=0, access=mmap.ACCESS_WRITE)
            server_epoch = new_nonzero_u64_token()
            _FILE_HEADER.pack_into(
                view,
                0,
                _FILE_MAGIC,
                _FILE_VERSION,
                self.slot_count,
                self.slot_payload_capacity_bytes,
                self.slot_stride,
                self.overflow_page_count,
                self.overflow_page_capacity_bytes,
                self.page_stride,
                self.max_overflow_pages_per_response,
                0,
            )
            for slot_index in range(self.slot_count):
                with _acquire_slot_guard(
                    path=self.path,
                    slot_index=slot_index,
                    deadline_ns=monotonic_ns() + 1_000_000_000,
                    poll_interval_seconds=self.poll_interval_seconds,
                ):
                    _clear_slot(
                        view,
                        slot_offset=_slot_offset(self.slot_stride, slot_index),
                        generation=new_nonzero_u64_token(),
                    )
                    _slot_lock_path(self.path, slot_index).unlink(missing_ok=True)
            for page_index in range(self.overflow_page_count):
                _clear_page(view, page_offset=self._page_offset(page_index))
            self._page_allocations.clear()
            self._page_pool_high_watermark = 0
            with self._metrics_lock:
                self._response_count = 0
                self._overflow_response_count = 0
                self._compressed_response_count = 0
                self._capacity_exhausted_count = 0
                self._response_raw_sizes.clear()
                self._response_raw_sizes_by_task.clear()
            _FILE_HEADER.pack_into(
                view,
                0,
                _FILE_MAGIC,
                _FILE_VERSION,
                self.slot_count,
                self.slot_payload_capacity_bytes,
                self.slot_stride,
                self.overflow_page_count,
                self.overflow_page_capacity_bytes,
                self.page_stride,
                self.max_overflow_pages_per_response,
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
        """停止请求消费并关闭 mmap。"""

        if self._instance_lock_file is None and self._mmap is None:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        view = self._mmap
        if view is not None:
            header = list(_FILE_HEADER.unpack_from(view, 0))
            header[9] = 0
            _FILE_HEADER.pack_into(view, 0, *header)
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
        view, file = self._mmap, self._file
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
        """扫描描述符并提交到有界线程池。"""

        view = self._mmap
        if view is None:
            return
        while not self._stop_event.is_set():
            dispatched = False
            now_ns = monotonic_ns()
            sweep_claims = now_ns >= self._next_abandoned_claim_sweep_ns
            if sweep_claims:
                self._next_abandoned_claim_sweep_ns = (
                    now_ns + _ABANDONED_CLAIM_SWEEP_INTERVAL_NS
                )
            for slot_index in range(self.slot_count):
                slot_offset = _slot_offset(self.slot_stride, slot_index)
                header = _SLOT_HEADER.unpack_from(view, slot_offset)
                state, generation, owner_token, deadline_ns, server_epoch = (
                    header[_SLOT_STATE_INDEX],
                    header[_SLOT_GENERATION_INDEX],
                    header[_SLOT_OWNER_INDEX],
                    header[_SLOT_DEADLINE_INDEX],
                    header[_SLOT_SERVER_EPOCH_INDEX],
                )
                if state == _STATE_FREE:
                    if sweep_claims:
                        self._reclaim_abandoned_claim(slot_index)
                    continue
                if state in (_STATE_ACKED, _STATE_CANCELLED):
                    if not self._is_active(slot_index):
                        self._reclaim_slot(
                            slot_index=slot_index,
                            generation=generation,
                            owner_token=owner_token,
                            allowed_states=(_STATE_ACKED, _STATE_CANCELLED),
                            require_expired=False,
                        )
                    continue
                if state == _STATE_REQUEST and now_ns >= deadline_ns:
                    self._reclaim_slot(
                        slot_index=slot_index,
                        generation=generation,
                        owner_token=owner_token,
                        allowed_states=(_STATE_REQUEST,),
                        require_expired=True,
                    )
                    continue
                if (
                    state == _STATE_RESPONSE
                    and now_ns >= deadline_ns + _RESPONSE_ACK_GRACE_NS
                ):
                    self._reclaim_slot(
                        slot_index=slot_index,
                        generation=generation,
                        owner_token=owner_token,
                        allowed_states=(_STATE_RESPONSE,),
                        require_expired=True,
                        deadline_grace_ns=_RESPONSE_ACK_GRACE_NS,
                    )
                    continue
                if state != _STATE_REQUEST or self._is_at_capacity(slot_index):
                    continue
                try:
                    with _acquire_slot_guard(
                        path=self.path,
                        slot_index=slot_index,
                        deadline_ns=monotonic_ns() + 10_000_000,
                        poll_interval_seconds=self.poll_interval_seconds,
                    ):
                        current = _SLOT_HEADER.unpack_from(view, slot_offset)
                        if (
                            current[_SLOT_STATE_INDEX] != _STATE_REQUEST
                            or current[_SLOT_GENERATION_INDEX] != generation
                            or current[_SLOT_OWNER_INDEX] != owner_token
                            or current[_SLOT_SERVER_EPOCH_INDEX] != server_epoch
                        ):
                            continue
                        if monotonic_ns() >= current[_SLOT_DEADLINE_INDEX]:
                            self._free_slot_locked(slot_index, generation)
                            continue
                        with self._active_lock:
                            if len(self._active_slots) >= self.max_concurrent_requests:
                                continue
                            self._active_slots.add(slot_index)
                        _publish_slot_state(
                            view,
                            slot_offset=slot_offset,
                            state=_STATE_PROCESSING,
                        )
                        request_size, request_crc, deadline_ns = (
                            current[_SLOT_REQUEST_SIZE_INDEX],
                            current[_SLOT_REQUEST_CRC_INDEX],
                            current[_SLOT_DEADLINE_INDEX],
                        )
                except _SlotGuardBusyError:
                    continue
                if self._executor is not None:
                    self._executor.submit(
                        self._process_slot,
                        slot_index=slot_index,
                        generation=generation,
                        owner_token=owner_token,
                        request_size=request_size,
                        request_crc=request_crc,
                        deadline_ns=deadline_ns,
                        server_epoch=server_epoch,
                    )
                    dispatched = True
            if not dispatched:
                self._stop_event.wait(self.poll_interval_seconds)

    def _process_slot(
        self,
        *,
        slot_index: int,
        generation: int,
        owner_token: int,
        request_size: int,
        request_crc: int,
        deadline_ns: int,
        server_epoch: int,
    ) -> None:
        """执行一个请求并发布内联或分页响应。"""

        view = self._mmap
        if view is None:
            return
        slot_offset = _slot_offset(self.slot_stride, slot_index)
        allocated_pages: list[int] = []
        try:
            if request_size <= 0 or request_size > self.slot_payload_capacity_bytes:
                raise InvalidRequestError("inference mmap 请求长度不合法")
            request_offset = slot_offset + _SLOT_HEADER.size
            encoded_request = bytes(
                view[request_offset : request_offset + request_size]
            )
            if crc32_ieee(encoded_request) != request_crc:
                raise InvalidRequestError("inference mmap 请求校验失败")
            request = _decode_payload(encoded_request)
            task_type = _read_request_task_type(request)
            try:
                _reject_inline_image_bytes(request)
                result = self.request_handler(request)
                if request.get("action") == "ping":
                    result = dict(result)
                    result["mailbox"] = self.get_health_summary()
                response = {"ok": True, "result": result}
            except Exception as error:  # noqa: BLE001 - IPC 边界统一序列化
                response = _error_response(error)
            raw_response = _encode_payload(response)
            observed_raw_response_size = len(raw_response)
            capacity_exhausted = False
            max_response_size = max(
                self.slot_payload_capacity_bytes,
                self.max_overflow_pages_per_response
                * self.overflow_page_capacity_bytes,
            )
            if len(raw_response) > max_response_size:
                capacity_exhausted = True
                raw_response = _encode_payload(
                    _error_response(
                        _MmapResponseCapacityExhaustedError(
                            "inference mmap 响应超过固定页池单请求上限",
                            details={
                                "response_size": len(raw_response),
                                "max_response_size": max_response_size,
                            },
                        )
                    )
                )
            encoded_response, flags = self._encode_response(raw_response)
            if len(encoded_response) > self.slot_payload_capacity_bytes:
                needed = (
                    len(encoded_response) + self.overflow_page_capacity_bytes - 1
                ) // self.overflow_page_capacity_bytes
                allocated_pages = self._allocate_pages(
                    slot_index=slot_index,
                    generation=generation,
                    owner_token=owner_token,
                    page_count=needed,
                )
                if not allocated_pages:
                    capacity_exhausted = True
                    encoded_response = _encode_payload(
                        _error_response(
                            _MmapResponseCapacityExhaustedError(
                                "inference mmap 固定溢出页池暂时不足",
                                details={
                                    "required_page_count": needed,
                                    "available_page_count": self._count_free_pages(),
                                },
                            )
                        )
                    )
                    raw_response = encoded_response
                    flags = 0
                else:
                    flags |= _FLAG_RESPONSE_OVERFLOW
                    self._write_pages(
                        page_indexes=allocated_pages,
                        slot_index=slot_index,
                        generation=generation,
                        owner_token=owner_token,
                        content=encoded_response,
                    )
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 1_000_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                current = _SLOT_HEADER.unpack_from(view, slot_offset)
                if (
                    current[_SLOT_STATE_INDEX] != _STATE_PROCESSING
                    or current[_SLOT_GENERATION_INDEX] != generation
                    or current[_SLOT_OWNER_INDEX] != owner_token
                    or current[_SLOT_SERVER_EPOCH_INDEX] != server_epoch
                    or monotonic_ns() >= current[_SLOT_DEADLINE_INDEX]
                ):
                    self._free_pages(allocated_pages)
                    return
                if not flags & _FLAG_RESPONSE_OVERFLOW:
                    response_offset = (
                        slot_offset
                        + _SLOT_HEADER.size
                        + self.slot_payload_capacity_bytes
                    )
                    view[response_offset : response_offset + len(encoded_response)] = (
                        encoded_response
                    )
                _SLOT_HEADER.pack_into(
                    view,
                    slot_offset,
                    _STATE_PROCESSING,
                    flags,
                    request_size,
                    request_crc,
                    len(encoded_response),
                    len(raw_response),
                    crc32_ieee(encoded_response),
                    allocated_pages[0] if allocated_pages else _NO_PAGE_INDEX,
                    len(allocated_pages),
                    generation,
                    owner_token,
                    current[_SLOT_DEADLINE_INDEX],
                    server_epoch,
                )
                _publish_slot_state(
                    view,
                    slot_offset=slot_offset,
                    state=_STATE_RESPONSE,
                )
            self._record_response_metrics(
                task_type=task_type,
                raw_size=observed_raw_response_size,
                compressed=bool(flags & _FLAG_RESPONSE_ZLIB),
                overflow=bool(flags & _FLAG_RESPONSE_OVERFLOW),
                capacity_exhausted=capacity_exhausted,
            )
            LOGGER.debug(
                "inference mmap response published",
                extra={
                    "slot_index": slot_index,
                    "raw_size": len(raw_response),
                    "encoded_size": len(encoded_response),
                    "compressed": bool(flags & _FLAG_RESPONSE_ZLIB),
                    "overflow_page_count": len(allocated_pages),
                },
            )
        except Exception as error:  # noqa: BLE001 - worker 异常必须收敛
            self._free_pages(allocated_pages)
            self._publish_internal_error(
                slot_index=slot_index,
                generation=generation,
                owner_token=owner_token,
                request_size=request_size,
                error=error,
            )
        finally:
            with self._active_lock:
                self._active_slots.discard(slot_index)

    def _encode_response(self, raw_response: bytes) -> tuple[bytes, int]:
        """大载荷仅在压缩至少降低 12.5% 时采用 zlib level 1。"""

        if len(raw_response) < self.compression_threshold_bytes:
            return raw_response, 0
        compressed = zlib.compress(raw_response, level=1)
        if len(compressed) * 8 <= len(raw_response) * 7:
            return compressed, _FLAG_RESPONSE_ZLIB
        return raw_response, 0

    def _record_response_metrics(
        self,
        *,
        task_type: str,
        raw_size: int,
        compressed: bool,
        overflow: bool,
        capacity_exhausted: bool,
    ) -> None:
        """记录当前 daemon epoch 的有界响应容量统计。"""

        with self._metrics_lock:
            self._response_count += 1
            self._overflow_response_count += int(overflow)
            self._compressed_response_count += int(compressed)
            self._capacity_exhausted_count += int(capacity_exhausted)
            self._response_raw_sizes.append(raw_size)
            task_sizes = self._response_raw_sizes_by_task.setdefault(
                task_type,
                deque(maxlen=4096),
            )
            task_sizes.append(raw_size)

    def _allocate_pages(
        self,
        *,
        slot_index: int,
        generation: int,
        owner_token: int,
        page_count: int,
    ) -> list[int]:
        """优先分配连续页，碎片化时使用任意空闲页。"""

        if page_count <= 0 or page_count > self.max_overflow_pages_per_response:
            return []
        view = self._mmap
        if view is None:
            return []
        with self._page_pool_lock:
            allocated_page_indexes = {
                page_index
                for allocation in self._page_allocations.values()
                for page_index in allocation
            }
            free = [
                index
                for index in range(self.overflow_page_count)
                if index not in allocated_page_indexes
                and _PAGE_HEADER.unpack_from(view, self._page_offset(index))[0]
                == _PAGE_FREE
            ]
            if len(free) < page_count:
                return []
            selected = list(
                select_page_indices(
                    free_page_indices=free,
                    page_count=page_count,
                )
            )
            for ordinal, page_index in enumerate(selected):
                next_page_index = (
                    selected[ordinal + 1]
                    if ordinal + 1 < len(selected)
                    else _NO_PAGE_INDEX
                )
                _PAGE_HEADER.pack_into(
                    view,
                    self._page_offset(page_index),
                    _PAGE_RESERVED,
                    next_page_index,
                    0,
                    0,
                    slot_index,
                    generation,
                    owner_token,
                )
            self._page_allocations[(slot_index, generation, owner_token)] = tuple(
                selected
            )
            used = self.overflow_page_count - len(free) + page_count
            self._page_pool_high_watermark = max(self._page_pool_high_watermark, used)
            return selected

    def _write_pages(
        self,
        *,
        page_indexes: list[int],
        slot_index: int,
        generation: int,
        owner_token: int,
        content: bytes,
    ) -> None:
        """逐页写正文和 metadata，最后发布 READY。"""

        view = self._mmap
        if view is None:
            raise ServiceConfigurationError("inference mmap 已关闭")
        for ordinal, page_index in enumerate(page_indexes):
            chunk = content[
                ordinal * self.overflow_page_capacity_bytes : (ordinal + 1)
                * self.overflow_page_capacity_bytes
            ]
            page_offset = self._page_offset(page_index)
            body_offset = page_offset + _PAGE_HEADER.size
            view[body_offset : body_offset + len(chunk)] = chunk
            _PAGE_HEADER.pack_into(
                view,
                page_offset,
                _PAGE_RESERVED,
                (
                    page_indexes[ordinal + 1]
                    if ordinal + 1 < len(page_indexes)
                    else _NO_PAGE_INDEX
                ),
                len(chunk),
                crc32_ieee(chunk),
                slot_index,
                generation,
                owner_token,
            )
            _PAGE_STATE.pack_into(view, page_offset, _PAGE_READY)

    def _publish_internal_error(
        self,
        *,
        slot_index: int,
        generation: int,
        owner_token: int,
        request_size: int,
        error: Exception,
    ) -> None:
        """将 daemon 内部异常收敛为必定可内联的错误响应。"""

        view = self._mmap
        if view is None:
            return
        encoded = _encode_payload(_error_response(error))
        if len(encoded) > self.slot_payload_capacity_bytes:
            encoded = b'{"ok":false,"error":{"code":"service_configuration_error","message":"inference mmap internal error"}}'
        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 1_000_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                slot_offset = _slot_offset(self.slot_stride, slot_index)
                current = _SLOT_HEADER.unpack_from(view, slot_offset)
                if (
                    current[_SLOT_GENERATION_INDEX] != generation
                    or current[_SLOT_OWNER_INDEX] != owner_token
                    or current[_SLOT_SERVER_EPOCH_INDEX] != self._server_epoch
                ):
                    return
                if (
                    current[_SLOT_STATE_INDEX] == _STATE_CANCELLED
                    or monotonic_ns() >= current[_SLOT_DEADLINE_INDEX]
                ):
                    return
                response_offset = (
                    slot_offset + _SLOT_HEADER.size + self.slot_payload_capacity_bytes
                )
                view[response_offset : response_offset + len(encoded)] = encoded
                _SLOT_HEADER.pack_into(
                    view,
                    slot_offset,
                    _STATE_PROCESSING,
                    0,
                    request_size,
                    current[_SLOT_REQUEST_CRC_INDEX],
                    len(encoded),
                    len(encoded),
                    crc32_ieee(encoded),
                    _NO_PAGE_INDEX,
                    0,
                    generation,
                    owner_token,
                    current[_SLOT_DEADLINE_INDEX],
                    current[_SLOT_SERVER_EPOCH_INDEX],
                )
                _publish_slot_state(
                    view,
                    slot_offset=slot_offset,
                    state=_STATE_RESPONSE,
                )
        except _SlotGuardBusyError:
            return

    def _reclaim_abandoned_claim(self, slot_index: int) -> bool:
        """回收 client 在发布 REQUEST 前崩溃留下的锁文件。"""

        lock_path = _slot_lock_path(self.path, slot_index)
        metadata = _read_slot_lock_metadata(lock_path)
        deadline = metadata.get("deadline_ns")
        if not isinstance(deadline, int) or monotonic_ns() < deadline:
            return False
        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 10_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                view = self._mmap
                if view is None:
                    return False
                if (
                    _SLOT_HEADER.unpack_from(
                        view,
                        _slot_offset(self.slot_stride, slot_index),
                    )[0]
                    != _STATE_FREE
                ):
                    return False
                if _read_slot_lock_metadata(lock_path) != metadata:
                    return False
                lock_path.unlink(missing_ok=True)
                return True
        except _SlotGuardBusyError:
            return False

    def _reclaim_slot(
        self,
        *,
        slot_index: int,
        generation: int,
        owner_token: int,
        allowed_states: tuple[int, ...],
        require_expired: bool,
        deadline_grace_ns: int = 0,
    ) -> bool:
        """在 guard 下按 generation/owner/deadline 回收描述符及其页。"""

        try:
            with _acquire_slot_guard(
                path=self.path,
                slot_index=slot_index,
                deadline_ns=monotonic_ns() + 10_000_000,
                poll_interval_seconds=self.poll_interval_seconds,
            ):
                view = self._mmap
                if view is None:
                    return False
                slot_offset = _slot_offset(self.slot_stride, slot_index)
                current = _SLOT_HEADER.unpack_from(view, slot_offset)
                if (
                    current[_SLOT_STATE_INDEX] not in allowed_states
                    or current[_SLOT_GENERATION_INDEX] != generation
                    or current[_SLOT_OWNER_INDEX] != owner_token
                    or current[_SLOT_SERVER_EPOCH_INDEX] != self._server_epoch
                ):
                    return False
                if (
                    require_expired
                    and monotonic_ns()
                    < current[_SLOT_DEADLINE_INDEX] + deadline_grace_ns
                ):
                    return False
                self._free_pages_for_owner(slot_index, generation, owner_token)
                self._free_slot_locked(slot_index, generation)
                return True
        except _SlotGuardBusyError:
            return False

    def _free_slot_locked(self, slot_index: int, generation: int) -> None:
        """清空已持有 guard 的描述符和 client 锁文件。"""

        view = self._mmap
        if view is None:
            return
        _clear_slot(
            view,
            slot_offset=_slot_offset(self.slot_stride, slot_index),
            generation=generation,
        )
        _slot_lock_path(self.path, slot_index).unlink(missing_ok=True)

    def _free_pages_for_owner(
        self,
        slot_index: int,
        generation: int,
        owner_token: int,
    ) -> None:
        """释放属于一个响应的全部固定页。"""

        view = self._mmap
        if view is None:
            return
        with self._page_pool_lock:
            allocation = self._page_allocations.pop(
                (slot_index, generation, owner_token),
                None,
            )
            if allocation is not None:
                for page_index in allocation:
                    _clear_page(view, page_offset=self._page_offset(page_index))
                return
            for page_index in range(self.overflow_page_count):
                page_offset = self._page_offset(page_index)
                header = _PAGE_HEADER.unpack_from(view, page_offset)
                if (
                    header[_PAGE_STATE_INDEX] != _PAGE_FREE
                    and header[_PAGE_DESCRIPTOR_INDEX] == slot_index
                    and header[_PAGE_GENERATION_INDEX] == generation
                    and header[_PAGE_OWNER_INDEX] == owner_token
                ):
                    _clear_page(view, page_offset=page_offset)

    def _free_pages(self, page_indexes: list[int]) -> None:
        """释放一组尚未发布或发布失败的固定页。"""

        view = self._mmap
        if view is None or not page_indexes:
            return
        with self._page_pool_lock:
            expected = tuple(page_indexes)
            for allocation_key, allocation in tuple(self._page_allocations.items()):
                if allocation == expected:
                    self._page_allocations.pop(allocation_key, None)
                    break
            for page_index in page_indexes:
                _clear_page(view, page_offset=self._page_offset(page_index))

    def _count_free_pages(self) -> int:
        """返回当前空闲页数。"""

        view = self._mmap
        if view is None:
            return 0
        with self._page_pool_lock:
            allocated_page_indexes = {
                page_index
                for allocation in self._page_allocations.values()
                for page_index in allocation
            }
            return sum(
                index not in allocated_page_indexes
                and _PAGE_HEADER.unpack_from(view, self._page_offset(index))[0]
                == _PAGE_FREE
                for index in range(self.overflow_page_count)
            )

    def _page_offset(self, page_index: int) -> int:
        """返回固定页在文件中的偏移。"""

        return self.page_region_offset + page_index * self.page_stride

    def _is_active(self, slot_index: int) -> bool:
        """返回描述符是否仍由执行线程持有。"""

        with self._active_lock:
            return slot_index in self._active_slots

    def _is_at_capacity(self, slot_index: int) -> bool:
        """返回执行池是否已满或该描述符已提交。"""

        with self._active_lock:
            return (
                len(self._active_slots) >= self.max_concurrent_requests
                or slot_index in self._active_slots
            )


def _slot_offset(slot_stride: int, slot_index: int) -> int:
    """返回描述符偏移。"""

    return _FILE_HEADER.size + slot_index * slot_stride


def _slot_lock_path(path: Path, slot_index: int) -> Path:
    """返回 client 声明文件路径。"""

    return path.with_name(f"{path.name}.slot-{slot_index}.lock")


def _slot_guard_path(path: Path, slot_index: int) -> Path:
    """返回描述符跨进程 guard 文件路径。"""

    return path.with_name(f"{path.name}.slot-{slot_index}.guard")


def _server_instance_lock_path(path: Path) -> Path:
    """返回 daemon 单实例锁文件路径。"""

    return path.with_name(f"{path.name}.server.lock")


def _acquire_server_instance_lock(path: Path) -> BinaryIO:
    """获取当前 mailbox 的 daemon 单实例锁。"""

    try:
        return acquire_mmap_owner_lock(_server_instance_lock_path(path))
    except MmapOwnerLockBusyError as error:
        raise ServiceConfigurationError(
            "inference mmap mailbox 已由另一个 daemon 实例占用",
            details={"path": str(path)},
        ) from error


def _release_server_instance_lock(lock_file: BinaryIO) -> None:
    """释放 daemon 单实例锁。"""

    release_mmap_owner_lock(lock_file)


def _read_server_epoch(view: mmap.mmap, *, path: Path) -> int:
    """读取并校验当前 daemon epoch。"""

    epoch = int(_FILE_HEADER.unpack_from(view, 0)[9])
    if epoch <= 0:
        raise OperationCancelledError(
            "inference daemon 正在初始化 mmap mailbox",
            details={"path": str(path), "retryable": True},
        )
    return epoch


def _read_slot_lock_metadata(lock_path: Path) -> dict[str, object]:
    """读取 client 声明元数据。"""

    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _acquire_slot_guard(
    *,
    path: Path,
    slot_index: int,
    deadline_ns: int,
    poll_interval_seconds: float,
) -> AbstractContextManager[None]:
    """跨平台获取一个描述符的短临界区锁。"""

    return acquire_mmap_guard(
        guard_path=_slot_guard_path(path, slot_index),
        deadline_ns=deadline_ns,
        poll_interval_seconds=poll_interval_seconds,
    )


def _clear_slot(view: mmap.mmap, *, slot_offset: int, generation: int) -> None:
    """清空描述符 metadata，generation 保持 fencing。"""

    _SLOT_HEADER.pack_into(
        view,
        slot_offset,
        _STATE_FREE,
        0,
        0,
        0,
        0,
        0,
        0,
        _NO_PAGE_INDEX,
        0,
        generation,
        0,
        0,
        0,
    )


def _clear_page(view: mmap.mmap, *, page_offset: int) -> None:
    """清空固定溢出页 metadata。"""

    _PAGE_HEADER.pack_into(
        view,
        page_offset,
        _PAGE_FREE,
        _NO_PAGE_INDEX,
        0,
        0,
        0,
        0,
        0,
    )


def _publish_slot_state(view: mmap.mmap, *, slot_offset: int, state: int) -> None:
    """最后单独发布描述符状态。"""

    publish_u32(view, offset=slot_offset, value=state)


def _encode_payload(payload: dict[str, object]) -> bytes:
    """将 JSON 对象编码为紧凑 UTF-8。"""

    try:
        return to_json(payload)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError("inference mmap payload 不是合法 JSON") from error


def _decode_payload(content: bytes) -> dict[str, object]:
    """解码 JSON 对象。"""

    try:
        payload = from_json(content)
    except ValueError as error:
        raise InvalidRequestError("inference mmap payload 不是合法 JSON") from error
    if not isinstance(payload, dict):
        raise InvalidRequestError("inference mmap payload 必须是 JSON 对象")
    return payload


def _read_request_task_type(payload: dict[str, object]) -> str:
    """从请求快照读取 task type；系统只读请求按 action 单独统计。"""

    process_config = payload.get("process_config")
    if isinstance(process_config, dict):
        for key in ("runtime_target_snapshot", "runtime_target"):
            runtime_target = process_config.get(key)
            if not isinstance(runtime_target, dict):
                continue
            task_type = runtime_target.get("task_type")
            if isinstance(task_type, str) and task_type.strip():
                normalized = task_type.strip().lower()
                return (
                    normalized
                    if normalized in _RESPONSE_METRIC_TASK_TYPES
                    else "unknown"
                )
    action = payload.get("action")
    if isinstance(action, str) and action in {"ping", "status", "health"}:
        return action
    return "unknown"


def _build_size_summary(values: deque[int]) -> dict[str, int | None]:
    """返回最近 4096 个响应原始 JSON 长度的确定性分位数。"""

    ordered = sorted(values)
    if not ordered:
        return {
            "sample_count": 0,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }

    def percentile(ratio: float) -> int:
        index = min(len(ordered) - 1, max(0, ceil(len(ordered) * ratio) - 1))
        return ordered[index]

    return {
        "sample_count": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def _reject_inline_image_bytes(payload: dict[str, object]) -> None:
    """禁止图片 bytes/base64 进入控制信息 mailbox。"""

    def contains_image_content(value: object) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {
                    "input_image_bytes_base64",
                    "preview_image_bytes_base64",
                } and child not in (None, ""):
                    return True
                if contains_image_content(child):
                    return True
        elif isinstance(value, list | tuple):
            return any(contains_image_content(child) for child in value)
        return False

    if contains_image_content(payload):
        raise InvalidRequestError(
            "inference mmap 只传控制信息，图片必须使用 LocalBuffer 引用"
        )


def _error_response(error: Exception) -> dict[str, object]:
    """把异常编码成控制客户端可恢复的错误 envelope。"""

    return {"ok": False, "error": serialize_error(error)}
