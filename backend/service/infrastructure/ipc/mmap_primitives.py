"""inference 与 Workflow mailbox 共用的中立 mmap IPC 原语。"""

from __future__ import annotations

import os
import errno
import struct
import sys
import zlib
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from secrets import randbits
from threading import Lock
from time import monotonic_ns, sleep
from typing import BinaryIO, TypeVar

from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path


_UINT32 = struct.Struct("<I")
_PageHeader = TypeVar("_PageHeader")


class MmapGuardBusyError(Exception):
    """表示 mmap 短临界区 guard 在 deadline 前不可用。"""


class MmapOwnerLockBusyError(Exception):
    """表示 mailbox owner lock 已由另一个进程持有。"""


class MmapGuardFileError(RuntimeError):
    """表示 guard 文件缺失、长度不符或已失去可信身份。"""


class MmapGuardPool:
    """在单个 mapping 生命周期内有界复用独立锁句柄，不共享活动 OFD 锁。"""

    def __init__(self, guard_path: str | Path, identity_file: BinaryIO) -> None:
        """固定 owner 已打开的文件身份；最多保留八个空闲句柄。"""
        self.path = Path(guard_path)
        identity = os.fstat(identity_file.fileno())
        self._identity = (identity.st_dev, identity.st_ino)
        self._size = identity.st_size
        self._idle: list[BinaryIO] = []
        self._active = 0
        self._closed = False
        self._lock = Lock()

    def borrow(self, *, guard_path: str | Path, minimum_size: int) -> BinaryIO:
        """立即租用独立 handle；每次仍检查文件长度，路径不匹配直接拒绝。"""
        if Path(guard_path) != self.path or minimum_size > self._size:
            raise MmapGuardFileError("guard pool 路径或 byte range 不匹配")
        with self._lock:
            if self._closed:
                raise MmapGuardFileError("guard pool 已关闭")
            handle = self._idle.pop() if self._idle else None
            self._active += 1
        try:
            if handle is None:
                handle = _open_existing_guard_range(self.path, minimum_size=self._size)
            actual = os.fstat(handle.fileno())
            if (actual.st_dev, actual.st_ino) != self._identity or actual.st_size != self._size:
                raise MmapGuardFileError("guard 文件身份或长度已变化")
            if os.name != "nt":
                # Windows 活动句柄禁止删除共享；POSIX 允许替换路径，缓存 inode 不能代替路径校验。
                try:
                    current = self.path.stat()
                except OSError as error:
                    raise MmapGuardFileError("guard 文件路径身份不可读取") from error
                if (current.st_dev, current.st_ino) != self._identity or current.st_size != self._size:
                    raise MmapGuardFileError("guard 文件路径身份或长度已变化")
            return handle
        except BaseException:
            if handle is not None:
                handle.close()
            with self._lock:
                self._active -= 1
            raise

    def release(self, handle: BinaryIO, *, reusable: bool = True) -> None:
        """归还已解锁句柄；超过固定缓存上限的句柄立即关闭。"""
        with self._lock:
            self._active -= 1
            if reusable and len(self._idle) < 8:
                self._idle.append(handle)
                return
        handle.close()

    def close(self) -> None:
        """活动锁未归还时拒绝关闭，禁止在操作仍使用 mapping 时释放 owner。"""
        with self._lock:
            if self._active:
                raise MmapGuardBusyError("guard pool 仍有活动操作")
            self._closed = True
            handles, self._idle = self._idle, []
        for handle in handles:
            handle.close()


class MmapOwnerLockHandle:
    """持有一个 owner lock，并提供线程安全且真正幂等的释放。"""

    def __init__(self, lock_file: BinaryIO) -> None:
        """接管已经取得 byte-range lock 的文件 handle。"""

        self._lock_file: BinaryIO | None = lock_file
        self._release_lock = Lock()

    @property
    def released(self) -> bool:
        """返回 owner lock 是否已经释放。"""

        with self._release_lock:
            return self._lock_file is None

    def release(self) -> None:
        """至多执行一次 unlock/close；进程退出仍由 OS 最终兜底。"""

        with self._release_lock:
            lock_file = self._lock_file
            if lock_file is None:
                return
            try:
                unlock_byte_range_file(lock_file)
            finally:
                try:
                    lock_file.close()
                finally:
                    self._lock_file = None


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
    # Windows 并发创建目录时 resolve 可返回带或不带 extended-length 前缀的同一路径。
    if not to_filesystem_path(path).is_relative_to(to_filesystem_path(root)):
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
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            raise BlockingIOError from error
        return
    _set_linux_handle_lock(guard_file, offset=offset, length=length, unlock=False)


def unlock_byte_range_file(
    guard_file: BinaryIO, *, offset: int = 0, length: int = 1
) -> None:
    """释放指定文件 byte range 的操作系统独占锁。"""

    if offset < 0 or length <= 0:
        raise ValueError("byte-range unlock 的 offset/length 不合法")
    guard_file.seek(offset)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(guard_file.fileno(), msvcrt.LK_UNLCK, length)
        return
    _set_linux_handle_lock(guard_file, offset=offset, length=length, unlock=True)


def _set_linux_handle_lock(guard_file: BinaryIO, *, offset: int, length: int, unlock: bool) -> None:
    """Linux 64-bit OFD 锁绑定独立 open handle，不因其他线程 close 同文件而消失。"""
    if not sys.platform.startswith("linux") or struct.calcsize("P") != 8:
        raise NotImplementedError("mmap byte-range guard 当前支持 Windows/Linux 64-bit")
    import fcntl

    # Linux x86_64/aarch64 的 struct flock：short、short、off_t、off_t、pid_t。
    # 仅支持该明确 ABI；不回退到有线程竞争漏洞的进程级 lockf。
    payload = struct.pack("@hhqqi4x", fcntl.F_UNLCK if unlock else fcntl.F_WRLCK,
                          os.SEEK_SET, offset, length, 0)
    fcntl.fcntl(guard_file.fileno(), fcntl.F_OFD_SETLK, payload)


def open_mmap_guard_identity(
    guard_path: str | Path,
    *,
    expected_size: int,
    create: bool,
) -> BinaryIO:
    """打开并持有固定 guard；只有未发布数据的 owner 可以创建或修复。"""

    if expected_size <= 0:
        raise ValueError("guard expected_size 必须大于 0")
    path = Path(guard_path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            guard_file = path.open("x+b", buffering=0)
        except FileExistsError:
            guard_file = path.open("r+b", buffering=0)
    else:
        try:
            guard_file = path.open("r+b", buffering=0)
        except FileNotFoundError as error:
            raise MmapGuardFileError(f"guard 文件不存在：{path}") from error
    actual_size = os.fstat(guard_file.fileno()).st_size
    if actual_size != expected_size:
        if not create:
            guard_file.close()
            raise MmapGuardFileError(
                f"guard 文件长度不匹配：expected={expected_size}, actual={actual_size}"
            )
        try:
            guard_file.truncate(expected_size)
            guard_file.flush()
            os.fsync(guard_file.fileno())
        except BaseException:
            guard_file.close()
            raise
    return guard_file


def _open_existing_guard_range(
    guard_path: str | Path,
    *,
    minimum_size: int,
) -> BinaryIO:
    """为一次短锁打开已有 guard，并拒绝任何隐式创建或扩容。"""

    path = Path(guard_path)
    try:
        guard_file = path.open("r+b", buffering=0)
    except FileNotFoundError as error:
        raise MmapGuardFileError(f"guard 文件不存在：{path}") from error
    actual_size = os.fstat(guard_file.fileno()).st_size
    if actual_size < minimum_size:
        guard_file.close()
        raise MmapGuardFileError(
            f"guard 文件长度不足：required={minimum_size}, actual={actual_size}"
        )
    return guard_file


@contextmanager
def acquire_mmap_guard(
    *,
    guard_path: str | Path,
    deadline_ns: int,
    poll_interval_seconds: float,
    offset: int = 0,
    length: int = 1,
    guard_pool: MmapGuardPool | None = None,
) -> Iterator[None]:
    """在 monotonic deadline 内取得一个跨进程短临界区 guard。"""

    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds 必须大于 0")
    # guard 位于每次 descriptor claim 的热路径；正式 path builder 已完成
    # containment 和绝对化，这里不能重复执行 Windows resolve/stat。
    path = Path(guard_path)
    guard_file = (
        _open_existing_guard_range(path, minimum_size=offset + length)
        if guard_pool is None
        else guard_pool.borrow(guard_path=path, minimum_size=offset + length)
    )
    acquired = False
    reusable = True
    try:
        while True:
            try:
                try_lock_byte_range_file(guard_file, offset=offset, length=length)
                acquired = True
                break
            except (BlockingIOError, OSError) as error:
                # 仅等待真实的锁竞争；无效句柄、磁盘故障等不能伪装为 busy。
                if not isinstance(error, BlockingIOError) and error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    reusable = False
                    raise
                if monotonic_ns() >= deadline_ns:
                    break
                sleep(poll_interval_seconds)
        if not acquired:
            raise MmapGuardBusyError
        yield
    finally:
        try:
            if acquired:
                reusable = False
                unlock_byte_range_file(guard_file, offset=offset, length=length)
                reusable = True
        finally:
            if guard_pool is None:
                guard_file.close()
            else:
                guard_pool.release(guard_file, reusable=reusable)


@contextmanager
def acquire_mmap_reader_guard(
    *,
    guard_path: str | Path,
    slot_count: int,
    deadline_ns: int,
    poll_interval_seconds: float,
    start_offset: int = 0,
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
    if start_offset < 0:
        raise ValueError("reader guard start_offset 不能小于 0")
    guard_file = _open_existing_guard_range(
        guard_path,
        minimum_size=start_offset + slot_count,
    )
    acquired_offset: int | None = None
    try:
        while acquired_offset is None:
            for offset in range(start_offset, start_offset + slot_count):
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
        try:
            if acquired_offset is not None:
                unlock_byte_range_file(guard_file, offset=acquired_offset, length=1)
        finally:
            guard_file.close()


def acquire_mmap_owner_lock(lock_path: str | Path) -> MmapOwnerLockHandle:
    """非阻塞取得 mailbox 单 owner lock，并由调用方持有返回的 handle。"""

    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+b", buffering=0)
    try:
        try_lock_byte_range_file(lock_file)
    except (BlockingIOError, OSError) as error:
        lock_file.close()
        if not isinstance(error, BlockingIOError) and error.errno not in {errno.EACCES, errno.EAGAIN}:
            raise
        raise MmapOwnerLockBusyError(f"mmap owner lock 已被占用：{path}") from error
    return MmapOwnerLockHandle(lock_file)


def release_mmap_owner_lock(lock_file: MmapOwnerLockHandle) -> None:
    """幂等语义地释放 owner lock handle。"""

    lock_file.release()


def is_mmap_owner_lock_held(
    lock_path: str | Path, *, expected_identity: tuple[int, int] | None = None
) -> bool:
    """只读观察 owner byte-range，不取得锁；身份或 I/O 不确定时抛出异常。"""
    path = Path(lock_path)
    with path.open("rb", buffering=0) as handle:
        opened = os.fstat(handle.fileno())
        identity = (opened.st_dev, opened.st_ino)
        if expected_identity is not None and identity != expected_identity:
            raise MmapGuardFileError("owner lock 文件身份已变化")
        held = _owner_lock_held_on_handle(handle)
        current = path.stat()
        if (current.st_dev, current.st_ino) != identity:
            raise MmapGuardFileError("owner lock 查询期间路径身份已变化")
        return held


def _owner_lock_held_on_handle(handle: BinaryIO) -> bool:
    """平台查询均不取得短暂锁，也不改变 publisher 的启动准入。"""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        content = ctypes.create_string_buffer(1)
        read_count = wintypes.DWORD()
        if _windows_owner_read_file()(
            msvcrt.get_osfhandle(handle.fileno()), content, 1,
            ctypes.byref(read_count), None,
        ):
            return False
        error = ctypes.get_last_error()
        if error == 33:  # ERROR_LOCK_VIOLATION；EACCES 还可能表示真实权限错误。
            return True
        raise ctypes.WinError(error)
    if not sys.platform.startswith("linux") or struct.calcsize("P") != 8:
        raise NotImplementedError("owner lock 观测当前支持 Windows/Linux 64-bit")
    import fcntl

    request = struct.pack("@hhqqi4x", fcntl.F_WRLCK, os.SEEK_SET, 0, 1, 0)
    response = fcntl.fcntl(handle.fileno(), fcntl.F_OFD_GETLK, request)
    lock_type = struct.unpack("@hhqqi4x", response)[0]
    if lock_type not in {fcntl.F_UNLCK, fcntl.F_WRLCK, fcntl.F_RDLCK}:
        raise MmapGuardFileError("owner lock 查询返回未知锁类型")
    return lock_type != fcntl.F_UNLCK


@lru_cache(maxsize=1)
def _windows_owner_read_file() -> Callable[..., int]:
    """复用带完整 64-bit handle 签名的 ReadFile，避免每次探测重建 DLL 包装。"""
    import ctypes
    from ctypes import wintypes

    read_file = ctypes.WinDLL("kernel32", use_last_error=True).ReadFile
    read_file.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    read_file.restype = wintypes.BOOL
    return read_file


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
