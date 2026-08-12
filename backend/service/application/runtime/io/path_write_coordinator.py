"""跨 Workflow、跨线程和跨进程的本地路径写协调。"""

from __future__ import annotations

import atexit
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import os
from pathlib import Path
from tempfile import gettempdir
from threading import RLock

from backend.service.application.runtime.resource_scope import (
    ResourceScope,
    create_process_resource_scope,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.execution.execution_control import (
    ExecutionControl,
    build_node_execution_control,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)


_PATH_COORDINATOR_RESOURCE_KEY = "runtime.io.path-write-coordinator"
_DEFAULT_PROCESS_SCOPE = create_process_resource_scope()
_LOCK_ROOT = Path(gettempdir()) / "amvision-path-locks"
atexit.register(_DEFAULT_PROCESS_SCOPE.close)


@dataclass
class _PathLockEntry:
    """保存规范化路径的进程内锁和引用计数。"""

    lock: RLock = field(default_factory=RLock)
    references: int = 0


class PathWriteCoordinator:
    """按稳定路径顺序协调进程内锁和操作系统文件锁。"""

    def __init__(self) -> None:
        """初始化空路径锁表。"""

        self._table_lock = RLock()
        self._entries: dict[str, _PathLockEntry] = {}

    @contextmanager
    def acquire(
        self,
        paths: Sequence[Path],
        *,
        control: ExecutionControl,
    ) -> Iterator[None]:
        """按规范化路径排序获取全部锁，退出时逆序释放。"""

        normalized_paths = tuple(sorted({_normalize_path(path) for path in paths}))
        entries = [(path, self._retain_entry(path)) for path in normalized_paths]
        acquired_entries: list[tuple[str, _PathLockEntry]] = []
        try:
            for normalized_path, entry in entries:
                _acquire_thread_lock(entry.lock, control=control)
                acquired_entries.append((normalized_path, entry))
            with ExitStack() as stack:
                for normalized_path, _entry in acquired_entries:
                    stack.enter_context(
                        _InterprocessPathLock(
                            normalized_path=normalized_path,
                            control=control,
                        )
                    )
                yield
        finally:
            for _normalized_path, entry in reversed(acquired_entries):
                entry.lock.release()
            for normalized_path, entry in entries:
                self._release_entry(normalized_path, entry)

    def close(self) -> None:
        """清理没有持有者的路径锁表。"""

        with self._table_lock:
            self._entries = {
                path: entry
                for path, entry in self._entries.items()
                if entry.references > 0
            }

    def _retain_entry(self, normalized_path: str) -> _PathLockEntry:
        """读取路径锁并增加引用计数。"""

        with self._table_lock:
            entry = self._entries.setdefault(normalized_path, _PathLockEntry())
            entry.references += 1
            return entry

    def _release_entry(
        self,
        normalized_path: str,
        entry: _PathLockEntry,
    ) -> None:
        """减少路径锁引用并移除空闲项。"""

        with self._table_lock:
            entry.references = max(0, entry.references - 1)
            if entry.references == 0 and self._entries.get(normalized_path) is entry:
                self._entries.pop(normalized_path, None)


class _InterprocessPathLock:
    """使用 sidecar 文件实现单机跨进程互斥。"""

    def __init__(self, *, normalized_path: str, control: ExecutionControl) -> None:
        self.normalized_path = normalized_path
        self.control = control
        self._file = None

    def __enter__(self) -> _InterprocessPathLock:
        """可取消地获取操作系统文件锁。"""

        _LOCK_ROOT.mkdir(parents=True, exist_ok=True)
        lock_name = sha256(self.normalized_path.encode("utf-8")).hexdigest()
        self._file = (_LOCK_ROOT / f"{lock_name}.lock").open("a+b")
        try:
            self._file.seek(0)
            if self._file.read(1) == b"":
                self._file.write(b"\0")
                self._file.flush()
            while True:
                self.control.raise_if_cancelled_or_expired()
                try:
                    _try_lock_file(self._file)
                    return self
                except OSError:
                    self.control.wait_interruptibly(0.05)
        except Exception:
            self._file.close()
            self._file = None
            raise

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """释放操作系统文件锁。"""

        if self._file is None:
            return
        try:
            _unlock_file(self._file)
        finally:
            self._file.close()
            self._file = None


@contextmanager
def acquire_path_write_locks(
    request: WorkflowNodeExecutionRequest,
    paths: Sequence[Path],
    *,
    timeout_seconds: float = 30.0,
) -> Iterator[None]:
    """通过当前 worker 的共享协调器获取路径写锁。"""

    control = build_node_execution_control(
        request,
        operation_timeout_seconds=timeout_seconds,
    )
    coordinator = _require_coordinator(_resolve_process_scope(request))
    with coordinator.acquire(paths, control=control):
        yield


def _resolve_process_scope(request: WorkflowNodeExecutionRequest) -> ResourceScope:
    """解析当前节点所属进程作用域。"""

    if isinstance(request.runtime_context, WorkflowServiceNodeRuntimeContext):
        return request.runtime_context.process_resource_scope
    return _DEFAULT_PROCESS_SCOPE


def _require_coordinator(scope: ResourceScope) -> PathWriteCoordinator:
    """返回当前进程唯一的路径写协调器。"""

    resource = scope.get_or_create(
        _PATH_COORDINATOR_RESOURCE_KEY,
        PathWriteCoordinator,
        lambda value: value.close(),
    )
    if not isinstance(resource, PathWriteCoordinator):
        raise RuntimeError("PathWriteCoordinator 资源类型无效")
    return resource


def _normalize_path(path: Path) -> str:
    """生成适合 Windows 和 POSIX 比较的稳定绝对路径。"""

    resolved = str(path.expanduser().resolve(strict=False))
    return os.path.normcase(os.path.normpath(resolved))


def _acquire_thread_lock(lock: RLock, *, control: ExecutionControl) -> None:
    """可取消地获取进程内 RLock。"""

    while True:
        control.raise_if_cancelled_or_expired()
        if lock.acquire(timeout=0.05):
            return


def _try_lock_file(file_object: object) -> None:
    """非阻塞获取当前平台的 1 字节文件锁。"""

    if os.name == "nt":
        import msvcrt

        file_object.seek(0)
        msvcrt.locking(file_object.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(file_object.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(file_object: object) -> None:
    """释放当前平台的文件锁。"""

    if os.name == "nt":
        import msvcrt

        file_object.seek(0)
        msvcrt.locking(file_object.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(file_object.fileno(), fcntl.LOCK_UN)


__all__ = ["PathWriteCoordinator", "acquire_path_write_locks"]
