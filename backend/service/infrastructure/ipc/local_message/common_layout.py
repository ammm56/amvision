"""LocalMessage common、RPC 和 EventRing 的 little-endian binary layout。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
import struct
from uuid import UUID

import psutil

from backend.contracts.ipc.local_message_profiles import (
    EventRingChannelProfile,
    RpcChannelProfile,
)
from backend.service.application.message_channels.errors import (
    ChannelCorruptMessageError,
)


FILE_MAGIC = b"AMVLMSG\0"
FILE_VERSION = 1
ENDIAN_MARKER = 0x01020304
COMMON_HEADER_SIZE = 256
RPC_HEADER_SIZE = 256
RPC_DESCRIPTOR_HEADER_SIZE = 256
RPC_DESCRIPTOR_EXTENSION_OFFSET = 104
RPC_DESCRIPTOR_EXTENSION_SIZE = (
    RPC_DESCRIPTOR_HEADER_SIZE - RPC_DESCRIPTOR_EXTENSION_OFFSET
)
RPC_PAGE_HEADER_SIZE = 64
EVENT_HEADER_SIZE = 256
EVENT_SLOT_HEADER_SIZE = 64

CHANNEL_KIND_RPC = 1
CHANNEL_KIND_EVENT = 2

FILE_FLAG_CLOSED = 1 << 0
RPC_FLAG_CANCEL_REQUESTED = 1 << 0
RPC_FLAG_ACKED = 1 << 1
RPC_FLAG_RESPONSE_COMPRESSED = 1 << 2
EVENT_FLAG_CLOSED = 1 << 0

RPC_STATE_FREE = 0
RPC_STATE_WRITING_REQUEST = 1
RPC_STATE_REQUEST = 2
RPC_STATE_PROCESSING = 3
RPC_STATE_RESPONSE = 4

PAGE_STATE_FREE = 0
PAGE_STATE_RESERVED = 1
PAGE_STATE_PUBLISHED = 2
NO_PAGE_INDEX = -1

RPC_ERROR_NONE = 0
RPC_ERROR_DEADLINE_EXCEEDED = 1
RPC_ERROR_CANCELLED = 2
RPC_ERROR_INVALID_MESSAGE = 3
RPC_ERROR_CAPACITY_EXHAUSTED = 4
RPC_ERROR_SERVER_FAILURE = 5

COMMON_HEADER = struct.Struct("<8sHHI32sQQQQII168x")
RPC_HEADER = struct.Struct("<IIIIIIIIIIIIQQQQ64s112x")
RPC_DESCRIPTOR_HEADER = struct.Struct("<IIQQ16sQQIIIIiIIIQQ152x")
RPC_PAGE_HEADER = struct.Struct("<IIIIQiIIQQ12x")
EVENT_HEADER = struct.Struct("<IIIIIIQQQQ16sQQ64s104x")
EVENT_SLOT_HEADER = struct.Struct("<QQIIQI28x")

assert COMMON_HEADER.size == COMMON_HEADER_SIZE
assert RPC_HEADER.size == RPC_HEADER_SIZE
assert RPC_DESCRIPTOR_HEADER.size == RPC_DESCRIPTOR_HEADER_SIZE
assert RPC_DESCRIPTOR_EXTENSION_SIZE == 152
assert RPC_PAGE_HEADER.size == RPC_PAGE_HEADER_SIZE
assert EVENT_HEADER.size == EVENT_HEADER_SIZE
assert EVENT_SLOT_HEADER.size == EVENT_SLOT_HEADER_SIZE


@dataclass(frozen=True, slots=True)
class CommonHeaderValue:
    """已校验的 common header。"""

    channel_kind: int
    layout_fingerprint: bytes
    channel_id: UUID
    owner_epoch: int
    owner_process_started_ns: int
    owner_pid: int
    flags: int


@dataclass(frozen=True, slots=True)
class RpcLayout:
    """由冻结 profile 推导的 RPC 文件布局。"""

    descriptor_stride_bytes: int
    descriptor_region_offset: int
    page_stride_bytes: int
    page_region_offset: int
    file_size_bytes: int
    fingerprint: bytes


@dataclass(frozen=True, slots=True)
class EventLayout:
    """由冻结 profile 推导的 EventRing 文件布局。"""

    slot_stride_bytes: int
    slot_region_offset: int
    file_size_bytes: int
    fingerprint: bytes


def rpc_layout(profile: RpcChannelProfile) -> RpcLayout:
    """返回 profile 对应的确定性 RPC layout。"""

    descriptor_stride = (
        RPC_DESCRIPTOR_HEADER_SIZE
        + profile.inline_request_capacity_bytes
        + profile.inline_response_capacity_bytes
    )
    descriptor_region = COMMON_HEADER_SIZE + RPC_HEADER_SIZE
    page_stride = RPC_PAGE_HEADER_SIZE + profile.overflow_page_capacity_bytes
    page_region = descriptor_region + profile.descriptor_count * descriptor_stride
    file_size = page_region + profile.overflow_page_count * page_stride
    fingerprint = _layout_fingerprint(
        kind="rpc",
        profile=asdict(profile),
        fixed={
            "common_header": COMMON_HEADER_SIZE,
            "rpc_header": RPC_HEADER_SIZE,
            "descriptor_header": RPC_DESCRIPTOR_HEADER_SIZE,
            "page_header": RPC_PAGE_HEADER_SIZE,
            "descriptor_stride": descriptor_stride,
            "page_stride": page_stride,
        },
    )
    return RpcLayout(
        descriptor_stride_bytes=descriptor_stride,
        descriptor_region_offset=descriptor_region,
        page_stride_bytes=page_stride,
        page_region_offset=page_region,
        file_size_bytes=file_size,
        fingerprint=fingerprint,
    )


def event_layout(profile: EventRingChannelProfile) -> EventLayout:
    """返回 profile 对应的确定性 EventRing layout。"""

    slot_stride = EVENT_SLOT_HEADER_SIZE + profile.payload_capacity_bytes
    slot_region = COMMON_HEADER_SIZE + EVENT_HEADER_SIZE
    file_size = slot_region + profile.slot_count * slot_stride
    fingerprint = _layout_fingerprint(
        kind="event",
        profile=asdict(profile),
        fixed={
            "common_header": COMMON_HEADER_SIZE,
            "event_header": EVENT_HEADER_SIZE,
            "slot_header": EVENT_SLOT_HEADER_SIZE,
            "slot_stride": slot_stride,
        },
    )
    return EventLayout(
        slot_stride_bytes=slot_stride,
        slot_region_offset=slot_region,
        file_size_bytes=file_size,
        fingerprint=fingerprint,
    )


def pack_common_header(
    *,
    channel_kind: int,
    fingerprint: bytes,
    channel_id: UUID,
    owner_epoch: int,
    flags: int = 0,
) -> bytes:
    """编码固定 256-byte common header。"""

    if len(fingerprint) != 32:
        raise ValueError("layout fingerprint 必须是 32 bytes")
    if owner_epoch <= 0:
        raise ValueError("owner_epoch 必须大于 0")
    return COMMON_HEADER.pack(
        FILE_MAGIC,
        FILE_VERSION,
        channel_kind,
        ENDIAN_MARKER,
        fingerprint,
        channel_id.int >> 64,
        channel_id.int & ((1 << 64) - 1),
        owner_epoch,
        int(psutil.Process(os.getpid()).create_time() * 1_000_000_000),
        os.getpid(),
        flags,
    )


def begin_owner_initialization(view: object, packed_header: bytes) -> None:
    """先发布新 epoch/closed fence，再初始化类型专属区域。

    已有 client 先看到新 epoch 并返回 ``ChannelRestarted``；随后打开的新 client
    看到 closed。首次创建时 magic 最后写入，owner 若在此前退出，下一 owner 可把
    未发布 header 当作空文件重新初始化。
    """

    if len(packed_header) != COMMON_HEADER_SIZE:
        raise ValueError("common header 长度不合法")
    current_magic = bytes(view[:8])
    if current_magic == FILE_MAGIC:
        # owner_epoch 位于 64；先 fence 旧 client，再阻止新 client claim。
        view[64:72] = packed_header[64:72]
        struct.pack_into("<I", view, 84, FILE_FLAG_CLOSED)
        closed_header = bytearray(packed_header)
        struct.pack_into("<I", closed_header, 84, FILE_FLAG_CLOSED)
        view[:COMMON_HEADER_SIZE] = closed_header
        return
    if current_magic != b"\0" * 8:
        raise ChannelCorruptMessageError("LocalMessage 未发布的 magic 已损坏")
    closed_header = bytearray(packed_header)
    struct.pack_into("<I", closed_header, 84, FILE_FLAG_CLOSED)
    view[8:COMMON_HEADER_SIZE] = closed_header[8:]
    view[:8] = FILE_MAGIC


def finish_owner_initialization(view: object) -> None:
    """类型专属 header/metadata 完成后最后发布 ready flags。"""

    struct.pack_into("<I", view, 84, 0)


def unpack_common_header(
    content: object,
    *,
    expected_kind: int,
    expected_fingerprint: bytes,
) -> CommonHeaderValue:
    """解码并严格验证 common header 与 layout fingerprint。"""

    try:
        (
            magic,
            version,
            channel_kind,
            endian,
            fingerprint,
            channel_id_high,
            channel_id_low,
            owner_epoch,
            owner_process_started_ns,
            owner_pid,
            flags,
        ) = COMMON_HEADER.unpack_from(content, 0)
    except (struct.error, TypeError) as error:
        raise ChannelCorruptMessageError("LocalMessage common header 不完整") from error
    if magic != FILE_MAGIC or version != FILE_VERSION:
        raise ChannelCorruptMessageError("LocalMessage magic/version 不兼容")
    if endian != ENDIAN_MARKER:
        raise ChannelCorruptMessageError("LocalMessage endian marker 不兼容")
    if channel_kind != expected_kind:
        raise ChannelCorruptMessageError("LocalMessage Channel kind 不匹配")
    if fingerprint != expected_fingerprint:
        raise ChannelCorruptMessageError("LocalMessage layout fingerprint 不匹配")
    if owner_epoch <= 0:
        raise ChannelCorruptMessageError("LocalMessage owner epoch 不合法")
    return CommonHeaderValue(
        channel_kind=channel_kind,
        layout_fingerprint=fingerprint,
        channel_id=UUID(int=(channel_id_high << 64) | channel_id_low),
        owner_epoch=owner_epoch,
        owner_process_started_ns=owner_process_started_ns,
        owner_pid=owner_pid,
        flags=flags,
    )


def encode_profile_id(profile_id: str) -> bytes:
    """把 profile id 编码为 header 内固定 64-byte ASCII 字段。"""

    encoded = profile_id.encode("ascii")
    if len(encoded) > 63:
        raise ValueError("profile_id 不能超过 63 ASCII bytes")
    return encoded.ljust(64, b"\0")


def decode_profile_id(value: bytes) -> str:
    """解码 header 中的 profile id。"""

    try:
        return value.rstrip(b"\0").decode("ascii")
    except UnicodeDecodeError as error:
        raise ChannelCorruptMessageError("LocalMessage profile_id 损坏") from error


def _layout_fingerprint(
    *, kind: str, profile: dict[str, object], fixed: dict[str, int]
) -> bytes:
    """计算跨语言可复现的 SHA-256 layout fingerprint。"""

    canonical = json.dumps(
        {"kind": kind, "profile": profile, "fixed": fixed},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).digest()
