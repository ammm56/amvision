"""跨进程 GPU/MIG 设备租约。

该模块只在训练、转换 attempt 和 deployment 进程生命周期边界使用。推理请求热路径
不得获取本模块的文件锁。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import os
from pathlib import Path
import subprocess
from threading import Lock, get_ident
from time import monotonic, sleep, time
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
    ServiceError,
)


_AUTO_DEVICE_NAMES = frozenset({"", "auto", "default"})
_CUDA_AUTO_DEVICE_NAMES = frozenset({"cuda", "gpu"})
_STABLE_RESOURCE_PREFIXES = ("GPU-", "MIG-")


class DeviceLeaseMode(StrEnum):
    """设备租约模式。"""

    SHARED = "shared"
    EXCLUSIVE = "exclusive"


class DeviceLeaseProviderConfig(BaseModel):
    """描述跨进程 GPU 资源协调配置。

    字段：
    - root_dir：所有 backend-service/backend-worker 进程共享的锁目录。
    - exclusive_acquire_timeout_seconds：训练和转换等待独占 GPU 的最长秒数；0 表示立即拒绝。
    - shared_acquire_timeout_seconds：deployment 启动等待共享 reservation 的最长秒数；0 表示立即拒绝。
    - poll_interval_seconds：等待 OS 文件锁时的轮询间隔。
    - cuda_device_uuid_overrides：可选的 ``cuda:n -> GPU-/MIG- UUID`` 显式映射。
    - conversion_cuda_device：TensorRT conversion 使用的 CUDA 设备。
    """

    root_dir: str = "./data/runtime/device-leases"
    exclusive_acquire_timeout_seconds: float = Field(default=0.0, ge=0.0)
    shared_acquire_timeout_seconds: float = Field(default=0.0, ge=0.0)
    poll_interval_seconds: float = Field(default=0.05, gt=0.0)
    cuda_device_uuid_overrides: dict[str, str] = Field(default_factory=dict)
    conversion_cuda_device: str = "cuda:0"


class DeviceLeaseUnavailableError(ServiceError):
    """表示 GPU 当前被不兼容的 shared/exclusive lease 占用。"""

    def __init__(
        self,
        message: str = "GPU 资源当前被其他任务占用",
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="device_lease_unavailable",
            status_code=409,
            details=details,
        )


@dataclass(frozen=True)
class CudaDeviceResource:
    """描述当前进程可见的一个 CUDA GPU 或 MIG 实例。"""

    cuda_index: int
    device_name: str
    resource_key: str


@dataclass(frozen=True)
class DeviceLeaseInfo:
    """描述一次已经获得的设备租约。"""

    requested_device: str | None
    resolved_device: str
    cuda_index: int | None
    resource_key: str | None
    mode: str
    purpose: str
    owner_id: str
    process_id: int
    thread_id: int
    acquired_at_unix: float
    waited_seconds: float

    def to_dict(self) -> dict[str, object]:
        """返回可写入任务 metadata 或 health 的诊断对象。"""

        return asdict(self)


class DeviceLease:
    """由 OS 文件句柄持有的 GPU/MIG 租约上下文。"""

    def __init__(
        self,
        *,
        provider: DeviceLeaseProvider,
        info: DeviceLeaseInfo,
        lock_handle: _DeviceLockHandle | None,
    ) -> None:
        self._provider = provider
        self.info = info
        self._lock_handle = lock_handle
        self._released = False

    @property
    def resolved_device(self) -> str:
        """返回实际设备名称。"""

        return self.info.resolved_device

    def release(self) -> None:
        """幂等释放租约；进程异常退出时由 OS 关闭句柄并自动释放。"""

        if self._released:
            return
        self._released = True
        self._provider._release(self)

    def __enter__(self) -> DeviceLease:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


class CudaDeviceResolver:
    """把进程内 ``cuda:n`` 解析为稳定 GPU UUID 或 MIG UUID。"""

    def __init__(self, *, uuid_overrides: dict[str, str] | None = None) -> None:
        self._uuid_overrides = {
            _normalize_cuda_device_name(name): _normalize_resource_key(resource_key)
            for name, resource_key in (uuid_overrides or {}).items()
        }

    def list_visible_devices(
        self,
        *,
        torch_module: Any | None = None,
    ) -> tuple[CudaDeviceResource, ...]:
        """返回当前 Python 进程可见的全部 CUDA 资源。"""

        torch = torch_module
        if torch is None:
            try:
                import torch as torch  # type: ignore[no-redef]
            except Exception:
                torch = None
        cuda = getattr(torch, "cuda", None) if torch is not None else None
        available = _call_bool(cuda, "is_available")
        count = _call_int(cuda, "device_count")
        if not available or count <= 0:
            return ()

        nvidia_smi_uuids: dict[int, str] | None = None
        resources: list[CudaDeviceResource] = []
        for cuda_index in range(count):
            device_name = f"cuda:{cuda_index}"
            resource_key = self._uuid_overrides.get(device_name)
            if resource_key is None:
                resource_key = _read_torch_device_uuid(cuda, cuda_index)
            if resource_key is None:
                resource_key = _read_visible_device_uuid(cuda_index)
            if resource_key is None:
                if nvidia_smi_uuids is None:
                    nvidia_smi_uuids = _read_nvidia_smi_gpu_uuids()
                physical_index = _read_visible_device_physical_index(cuda_index)
                resource_key = nvidia_smi_uuids.get(
                    cuda_index if physical_index is None else physical_index
                )
            if resource_key is None:
                raise ServiceConfigurationError(
                    "无法把 CUDA 设备解析为稳定 GPU/MIG UUID",
                    details={
                        "device": device_name,
                        "cuda_visible_devices": os.environ.get(
                            "CUDA_VISIBLE_DEVICES"
                        ),
                        "required_resource_key_prefixes": list(
                            _STABLE_RESOURCE_PREFIXES
                        ),
                    },
                )
            resources.append(
                CudaDeviceResource(
                    cuda_index=cuda_index,
                    device_name=device_name,
                    resource_key=_normalize_resource_key(resource_key),
                )
            )
        return tuple(resources)

    def resolve(
        self,
        device_name: str,
        *,
        torch_module: Any | None = None,
    ) -> CudaDeviceResource:
        """解析并校验指定 ``cuda:n``。"""

        normalized = _normalize_cuda_device_name(device_name)
        cuda_index = int(normalized.split(":", 1)[1])
        resources = self.list_visible_devices(torch_module=torch_module)
        if cuda_index < 0 or cuda_index >= len(resources):
            raise InvalidRequestError(
                "CUDA 设备索引超出当前可见范围",
                details={"device": device_name, "cuda_count": len(resources)},
            )
        return resources[cuda_index]


class DeviceLeaseProvider:
    """使用 OS shared/exclusive 文件锁协调跨进程 GPU 资源。"""

    def __init__(
        self,
        *,
        root_dir: str | Path,
        poll_interval_seconds: float = 0.05,
        resolver: CudaDeviceResolver | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.resolver = resolver or CudaDeviceResolver()
        self._active: dict[str, DeviceLeaseInfo] = {}
        self._active_lock = Lock()

    @classmethod
    def from_config(cls, config: DeviceLeaseProviderConfig) -> DeviceLeaseProvider:
        """从统一配置创建 provider。"""

        return cls(
            root_dir=config.root_dir,
            poll_interval_seconds=config.poll_interval_seconds,
            resolver=CudaDeviceResolver(
                uuid_overrides=config.cuda_device_uuid_overrides
            ),
        )

    def acquire_cuda(
        self,
        requested_device: str | None,
        *,
        mode: DeviceLeaseMode,
        purpose: str,
        owner_id: str,
        timeout_seconds: float,
        torch_module: Any | None = None,
    ) -> DeviceLease:
        """获取 CUDA 设备 lease；``auto`` 会选择第一张可获得的可见 GPU。"""

        requested = (requested_device or "auto").strip()
        normalized = requested.lower()
        if normalized == "cpu":
            return self.cpu_lease(
                requested_device=requested_device,
                purpose=purpose,
                owner_id=owner_id,
            )
        resources = self.resolver.list_visible_devices(torch_module=torch_module)
        if normalized in _AUTO_DEVICE_NAMES:
            if not resources:
                return self.cpu_lease(
                    requested_device=requested_device,
                    purpose=purpose,
                    owner_id=owner_id,
                )
            return self._acquire_first_available(
                resources,
                requested_device=requested_device,
                mode=mode,
                purpose=purpose,
                owner_id=owner_id,
                timeout_seconds=timeout_seconds,
            )
        if normalized in _CUDA_AUTO_DEVICE_NAMES:
            if not resources:
                raise InvalidRequestError(
                    "当前运行环境没有可用 CUDA 设备，不能选择 CUDA 设备"
                )
            return self._acquire_first_available(
                resources,
                requested_device=requested_device,
                mode=mode,
                purpose=purpose,
                owner_id=owner_id,
                timeout_seconds=timeout_seconds,
            )
        if normalized.startswith("cuda:"):
            resource = self.resolver.resolve(normalized, torch_module=torch_module)
            return self.acquire_resource(
                resource,
                requested_device=requested_device,
                mode=mode,
                purpose=purpose,
                owner_id=owner_id,
                timeout_seconds=timeout_seconds,
            )
        raise InvalidRequestError(
            "不支持的 CUDA 设备名称",
            details={"device": requested_device},
        )

    def acquire_resource(
        self,
        resource: CudaDeviceResource,
        *,
        requested_device: str | None,
        mode: DeviceLeaseMode,
        purpose: str,
        owner_id: str,
        timeout_seconds: float,
    ) -> DeviceLease:
        """为一个已解析的稳定资源键获取 OS lease。"""

        if timeout_seconds < 0:
            raise ValueError("timeout_seconds 不能小于 0")
        started_at = monotonic()
        lock_path = self._lock_path(resource.resource_key)
        while True:
            handle = _DeviceLockHandle(lock_path)
            if handle.try_acquire(mode):
                info = DeviceLeaseInfo(
                    requested_device=requested_device,
                    resolved_device=resource.device_name,
                    cuda_index=resource.cuda_index,
                    resource_key=resource.resource_key,
                    mode=mode.value,
                    purpose=purpose,
                    owner_id=owner_id,
                    process_id=os.getpid(),
                    thread_id=get_ident(),
                    acquired_at_unix=time(),
                    waited_seconds=monotonic() - started_at,
                )
                lease = DeviceLease(provider=self, info=info, lock_handle=handle)
                with self._active_lock:
                    self._active[f"{owner_id}:{uuid4().hex}"] = info
                return lease
            handle.close()
            elapsed = monotonic() - started_at
            if elapsed >= timeout_seconds:
                raise DeviceLeaseUnavailableError(
                    "GPU 资源与当前运行中的任务或 deployment 冲突",
                    details={
                        "requested_device": requested_device,
                        "resolved_device": resource.device_name,
                        "resource_key": resource.resource_key,
                        "requested_mode": mode.value,
                        "purpose": purpose,
                        "owner_id": owner_id,
                        "timeout_seconds": timeout_seconds,
                        "waited_seconds": elapsed,
                        "lock_path": lock_path.as_posix(),
                    },
                )
            sleep(min(self.poll_interval_seconds, timeout_seconds - elapsed))

    def cpu_lease(
        self,
        *,
        requested_device: str | None,
        purpose: str,
        owner_id: str,
    ) -> DeviceLease:
        """返回不获取 OS 锁的 CPU lease。"""

        return DeviceLease(
            provider=self,
            info=DeviceLeaseInfo(
                requested_device=requested_device,
                resolved_device="cpu",
                cuda_index=None,
                resource_key=None,
                mode="none",
                purpose=purpose,
                owner_id=owner_id,
                process_id=os.getpid(),
                thread_id=get_ident(),
                acquired_at_unix=time(),
                waited_seconds=0.0,
            ),
            lock_handle=None,
        )

    def snapshot(self) -> dict[str, object]:
        """返回当前进程由本 provider 持有的租约诊断。"""

        with self._active_lock:
            active = tuple(self._active.values())
        return {
            "provider": "os-file-lock",
            "root_dir": self.root_dir.as_posix(),
            "process_id": os.getpid(),
            "active_lease_count": len(active),
            "active_leases": [item.to_dict() for item in active],
        }

    def _acquire_first_available(
        self,
        resources: tuple[CudaDeviceResource, ...],
        *,
        requested_device: str | None,
        mode: DeviceLeaseMode,
        purpose: str,
        owner_id: str,
        timeout_seconds: float,
    ) -> DeviceLease:
        """在总 timeout 内轮询全部可见设备，避免只等待 cuda:0。"""

        started_at = monotonic()
        while True:
            for resource in resources:
                try:
                    return self.acquire_resource(
                        resource,
                        requested_device=requested_device,
                        mode=mode,
                        purpose=purpose,
                        owner_id=owner_id,
                        timeout_seconds=0.0,
                    )
                except DeviceLeaseUnavailableError:
                    continue
            elapsed = monotonic() - started_at
            if elapsed >= timeout_seconds:
                raise DeviceLeaseUnavailableError(
                    "当前没有可获得的 CUDA GPU/MIG 资源",
                    details={
                        "requested_device": requested_device,
                        "requested_mode": mode.value,
                        "purpose": purpose,
                        "owner_id": owner_id,
                        "timeout_seconds": timeout_seconds,
                        "visible_resources": [
                            asdict(resource) for resource in resources
                        ],
                    },
                )
            sleep(min(self.poll_interval_seconds, timeout_seconds - elapsed))

    def _lock_path(self, resource_key: str) -> Path:
        digest = hashlib.sha256(resource_key.encode("utf-8")).hexdigest()
        return self.root_dir / f"{digest}.lease"

    def _release(self, lease: DeviceLease) -> None:
        handle = lease._lock_handle
        if handle is not None:
            handle.close()
        with self._active_lock:
            matching_keys = tuple(
                key
                for key, info in self._active.items()
                if info is lease.info
            )
            for key in matching_keys:
                self._active.pop(key, None)


class _DeviceLockHandle:
    """一个文件句柄上的单字节 shared/exclusive OS 锁。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("a+b", buffering=0)
        self._locked = False
        self._windows_overlapped: object | None = None

    def try_acquire(self, mode: DeviceLeaseMode) -> bool:
        if os.name == "nt":
            acquired, overlapped = _try_lock_windows(self._stream, mode)
            self._windows_overlapped = overlapped
        else:
            acquired = _try_lock_posix(self._stream, mode)
        self._locked = acquired
        return acquired

    def close(self) -> None:
        try:
            if self._locked:
                if os.name == "nt":
                    _unlock_windows(self._stream, self._windows_overlapped)
                else:
                    _unlock_posix(self._stream)
        finally:
            # 即使显式 unlock 报错，关闭 OS handle 也必须执行；这是进程崩溃和
            # 异常清理能够自动释放 lease 的最后保障。
            self._locked = False
            self._stream.close()


def _try_lock_posix(stream: Any, mode: DeviceLeaseMode) -> bool:
    import fcntl

    flags = fcntl.LOCK_SH if mode is DeviceLeaseMode.SHARED else fcntl.LOCK_EX
    try:
        fcntl.flock(stream.fileno(), flags | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _unlock_posix(stream: Any) -> None:
    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _try_lock_windows(
    stream: Any,
    mode: DeviceLeaseMode,
) -> tuple[bool, object]:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = (
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        )

    lock_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).LockFileEx
    lock_file_ex.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(Overlapped),
    )
    lock_file_ex.restype = wintypes.BOOL
    overlapped = Overlapped()
    flags = 0x00000001
    if mode is DeviceLeaseMode.EXCLUSIVE:
        flags |= 0x00000002
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
    if lock_file_ex(handle, flags, 0, 1, 0, ctypes.byref(overlapped)):
        return True, overlapped
    error_code = ctypes.get_last_error()
    if error_code in {32, 33, 158}:
        return False, overlapped
    raise ctypes.WinError(error_code)


def _unlock_windows(stream: Any, raw_overlapped: object | None) -> None:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    if raw_overlapped is None:
        return
    unlock_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).UnlockFileEx
    unlock_file_ex.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    unlock_file_ex.restype = wintypes.BOOL
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
    if not unlock_file_ex(handle, 0, 1, 0, ctypes.byref(raw_overlapped)):
        error_code = ctypes.get_last_error()
        raise ctypes.WinError(error_code)


def _call_bool(instance: object | None, method_name: str) -> bool:
    method = getattr(instance, method_name, None)
    return bool(method()) if callable(method) else False


def _call_int(instance: object | None, method_name: str) -> int:
    method = getattr(instance, method_name, None)
    return max(0, int(method())) if callable(method) else 0


def _read_torch_device_uuid(cuda: object, cuda_index: int) -> str | None:
    get_properties = getattr(cuda, "get_device_properties", None)
    if not callable(get_properties):
        return None
    try:
        properties = get_properties(cuda_index)
    except Exception:
        return None
    for attribute in ("uuid", "gpu_uuid"):
        raw_value = getattr(properties, attribute, None)
        value = _normalize_optional_uuid(raw_value)
        if value is not None:
            return value
    return None


def _read_visible_device_uuid(cuda_index: int) -> str | None:
    raw = os.environ.get("CUDA_VISIBLE_DEVICES")
    if not raw:
        return None
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    if cuda_index >= len(values):
        return None
    return _normalize_optional_uuid(values[cuda_index])


def _read_visible_device_physical_index(cuda_index: int) -> int | None:
    """把 CUDA 可见索引换算为 nvidia-smi 的物理 GPU 索引。"""

    raw = os.environ.get("CUDA_VISIBLE_DEVICES")
    if not raw:
        return None
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    if cuda_index >= len(values):
        return None
    try:
        physical_index = int(values[cuda_index])
    except ValueError:
        return None
    return physical_index if physical_index >= 0 else None


def _read_nvidia_smi_gpu_uuids() -> dict[int, str]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    resolved: dict[int, str] = {}
    for line in completed.stdout.splitlines():
        parts = tuple(part.strip() for part in line.split(",", 1))
        if len(parts) != 2:
            continue
        try:
            index = int(parts[0])
            resource_key = _normalize_resource_key(parts[1])
        except (TypeError, ValueError):
            continue
        resolved[index] = resource_key
    return resolved


def _normalize_optional_uuid(value: object) -> str | None:
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized.startswith(_STABLE_RESOURCE_PREFIXES):
        return normalized
    return None


def _normalize_resource_key(value: object) -> str:
    normalized = _normalize_optional_uuid(value)
    if normalized is None:
        raise ValueError("GPU 资源键必须是 GPU UUID 或 MIG UUID")
    return normalized


def _normalize_cuda_device_name(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized.startswith("cuda:"):
        raise ValueError("CUDA 设备映射键必须使用 cuda:<index>")
    try:
        index = int(normalized.split(":", 1)[1])
    except ValueError as error:
        raise ValueError("CUDA 设备索引必须是整数") from error
    if index < 0:
        raise ValueError("CUDA 设备索引不能小于 0")
    return f"cuda:{index}"


__all__ = [
    "CudaDeviceResolver",
    "CudaDeviceResource",
    "DeviceLease",
    "DeviceLeaseInfo",
    "DeviceLeaseMode",
    "DeviceLeaseProvider",
    "DeviceLeaseProviderConfig",
    "DeviceLeaseUnavailableError",
]
