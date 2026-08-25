"""inference 与 Workflow mailbox 共用的中立 mmap IPC 原语。"""

from __future__ import annotations

import os
import struct
import zlib
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from secrets import randbits
from time import monotonic_ns, sleep
from typing import BinaryIO, TypeVar


_UINT32 = struct.Struct("<I")
_PageHeader = TypeVar("_PageHeader")


class MmapGuardBusyError(Exception):
    """表示 mmap 短临界区 guard 在 deadline 前不可用。"""


class MmapOwnerLockBusyError(Exception):
    """表示 mailbox owner lock 已由另一个进程持有。"""


class MmapPageChainError(ValueError):
    """表示 page-chain 循环、越界或长度不一致。"""

    def __init__(self, reason: str, *, page_index: int) -> None:
        """保存稳定原因和发生错误的 page index。"""

        super().__init__(reason)
        self.reason = reason
        self.page_index = page_index


def crc32_ieee(content: bytes | bytearray | memoryview, value: int = 0) -> int:
    """按冻结的 CRC32 IEEE 算法增量计算无符号 32-bit checksum。"""

    return zlib.crc32(content, value) & 0xFFFFFFFF


def new_nonzero_u64_token() -> int:
    """生成用于 epoch、generation 或 owner 的非零 uint64 token。"""

    return randbits(64) or 1


def publish_u32(view: object, *, offset: int, value: int) -> None:
    """在 body 和 metadata 完成后最后发布一个 little-endian uint32。"""

    _UINT32.pack_into(view, offset, value)


def build_contained_mmap_path(
    *, root_dir: str | Path, relative_path: str | Path
) -> Path:
    """构造并校验始终位于指定 root 内的 mmap 路径。"""

    root = Path(root_dir).expanduser().resolve()
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ValueError("mmap relative_path 不能是绝对路径")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("mmap 路径必须位于配置 root 内")
    return path


def try_lock_byte_range_file(
    guard_file: BinaryIO, *, offset: int = 0, length: int = 1
) -> None:
    """使用操作系统锁非阻塞取得指定文件 byte range 的独占权。"""

    if offset < 0 or length <= 0:
        raise ValueError("byte-range lock 的 offset/length 不合法")
    guard_file.seek(offset)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(guard_file.fileno(), msvcrt.LK_NBLCK, length)
        except OSError as error:
            raise BlockingIOError from error
        return
    import fcntl

    fcntl.lockf(
        guard_file.fileno(),
        fcntl.LOCK_EX | fcntl.LOCK_NB,
        length,
        offset,
        os.SEEK_SET,
    )


def unlock_byte_range_file(
    guard_file: BinaryIO, *, offset: int = 0, length: int = 1
) -> None:
    """释放指定文件 byte range 的操作系统独占锁。"""

    if offset < 0 or length <= 0:
        raise ValueError("byte-range unlock 的 offset/length 不合法")
    guard_file.seek(offset)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(guard_file.fileno(), msvcrt.LK_UNLCK, length)
        except OSError:
            pass
        return
    import fcntl

    fcntl.lockf(
        guard_file.fileno(),
        fcntl.LOCK_UN,
        length,
        offset,
        os.SEEK_SET,
    )


@contextmanager
def acquire_mmap_guard(
    *,
    guard_path: str | Path,
    deadline_ns: int,
    poll_interval_seconds: float,
    offset: int = 0,
    length: int = 1,
) -> Iterator[None]:
    """在 monotonic deadline 内取得一个跨进程短临界区 guard。"""

    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds 必须大于 0")
    # guard 位于每次 descriptor claim 的热路径；正式 path builder 已完成
    # containment 和绝对化，这里不能重复执行 Windows resolve/stat。
    path = Path(guard_path)
    # 正式 mailbox/LocalBuffer guard 在 owner 启动时一次性创建。正常请求只
    # 打开已有文件，避免每次短临界区都触发 CreateDirectory/OpenOrCreate 的
    # NTFS 元数据路径；独立测试或首次初始化仍允许一次性回退创建。
    try:
        guard_file = path.open("r+b", buffering=0)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        guard_file = path.open("a+b", buffering=0)
        if os.fstat(guard_file.fileno()).st_size < offset + length:
            guard_file.truncate(offset + length)
    acquired = False
    try:
        while True:
            try:
                try_lock_byte_range_file(guard_file, offset=offset, length=length)
                acquired = True
                break
            except (BlockingIOError, OSError):
                if monotonic_ns() >= deadline_ns:
                    break
                sleep(poll_interval_seconds)
        if not acquired:
            raise MmapGuardBusyError
        yield
    finally:
        if acquired:
            unlock_byte_range_file(guard_file, offset=offset, length=length)
        guard_file.close()


@contextmanager
def acquire_mmap_reader_guard(
    *,
    guard_path: str | Path,
    slot_count: int,
    deadline_ns: int,
    poll_interval_seconds: float,
) -> Iterator[None]:
    """从固定 byte-range 中取得一个共享 reader guard 槽位。

    每个 reader 独占一个 byte；Broker 回收时尝试锁住完整 range，因此任意
    reader 尚未释放都会阻止物理 slot 被复用。取得 guard 后调用方仍必须再次
    校验 BufferRef generation，关闭“先校验、后加锁”之间的复用窗口。
    """

    if slot_count <= 0:
        raise ValueError("reader guard slot_count 必须大于 0")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds 必须大于 0")
    path = Path(guard_path)
    try:
        guard_file = path.open("r+b", buffering=0)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        guard_file = path.open("a+b", buffering=0)
        if os.fstat(guard_file.fileno()).st_size < slot_count:
            guard_file.truncate(slot_count)
    acquired_offset: int | None = None
    try:
        while acquired_offset is None:
            for offset in range(slot_count):
                try:
                    try_lock_byte_range_file(guard_file, offset=offset, length=1)
                except (BlockingIOError, OSError):
                    continue
                acquired_offset = offset
                break
            if acquired_offset is not None:
                break
            if monotonic_ns() >= deadline_ns:
                raise MmapGuardBusyError
            sleep(poll_interval_seconds)
        yield
    finally:
        if acquired_offset is not None:
            unlock_byte_range_file(guard_file, offset=acquired_offset, length=1)
        guard_file.close()


def acquire_mmap_owner_lock(lock_path: str | Path) -> BinaryIO:
    """非阻塞取得 mailbox 单 owner lock，并由调用方持有返回的 handle。"""

    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+b", buffering=0)
    try:
        try_lock_byte_range_file(lock_file)
    except (BlockingIOError, OSError) as error:
        lock_file.close()
        raise MmapOwnerLockBusyError from error
    return lock_file


def release_mmap_owner_lock(lock_file: BinaryIO) -> None:
    """幂等语义地释放 owner lock handle。"""

    try:
        unlock_byte_range_file(lock_file)
    finally:
        lock_file.close()


def select_page_indices(
    *, free_page_indices: Sequence[int], page_count: int
) -> tuple[int, ...]:
    """连续页优先；碎片化时选择任意固定数量空闲页。"""

    if page_count <= 0:
        return ()
    free = tuple(sorted(set(free_page_indices)))
    if len(free) < page_count:
        return ()
    for start in range(0, len(free) - page_count + 1):
        candidate = free[start : start + page_count]
        if candidate[-1] - candidate[0] == page_count - 1:
            return candidate
    return free[:page_count]


def read_page_chain(
    *,
    first_page_index: int,
    expected_page_count: int,
    total_page_count: int,
    no_page_index: int,
    read_header: Callable[[int], tuple[int, _PageHeader]],
) -> tuple[tuple[int, _PageHeader], ...]:
    """读取并验证固定长度 page-chain，不解释协议专属 header 内容。"""

    entries: list[tuple[int, _PageHeader]] = []
    seen: set[int] = set()
    page_index = first_page_index
    for ordinal in range(expected_page_count):
        if page_index in seen or not 0 <= page_index < total_page_count:
            raise MmapPageChainError("cycle_or_out_of_bounds", page_index=page_index)
        seen.add(page_index)
        next_page_index, header = read_header(page_index)
        entries.append((page_index, header))
        if ordinal < expected_page_count - 1 and next_page_index == no_page_index:
            raise MmapPageChainError("ended_early", page_index=page_index)
        if ordinal == expected_page_count - 1 and next_page_index != no_page_index:
            raise MmapPageChainError("too_long", page_index=page_index)
        page_index = next_page_index
    return tuple(entries)
