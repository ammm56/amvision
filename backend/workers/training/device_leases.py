"""训练 worker 内的单机 CUDA 设备租约。"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from threading import Condition
from typing import Any

from backend.service.application.errors import InvalidRequestError


_AUTO_DEVICE_NAMES = {"", "auto", "default"}
_CUDA_AUTO_DEVICE_NAMES = {"cuda", "gpu"}


@dataclass(frozen=True)
class TrainingDeviceLeaseInfo:
    """描述一次训练设备租约。

    字段：
    - requested_device：用户提交的设备名称。
    - resolved_device：实际分配给本次训练的设备名称。
    - cuda_index：CUDA 设备索引；CPU 训练时为空。
    - waited_seconds：等待空闲设备的耗时。
    """

    requested_device: str | None
    resolved_device: str
    cuda_index: int | None
    waited_seconds: float


class TrainingDeviceLease:
    """单次训练设备租约上下文。"""

    def __init__(
        self,
        *,
        manager: TrainingDeviceLeaseManager,
        info: TrainingDeviceLeaseInfo,
    ) -> None:
        """初始化租约上下文。"""

        self._manager = manager
        self.info = info
        self._released = False

    @property
    def resolved_device(self) -> str:
        """返回本次训练实际使用的设备名称。"""

        return self.info.resolved_device

    def release(self) -> None:
        """释放本次租约。"""

        if self._released:
            return
        self._released = True
        self._manager.release(self.info.cuda_index)

    def __enter__(self) -> TrainingDeviceLease:
        """进入上下文。"""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """退出上下文时释放租约。"""

        self.release()


class TrainingDeviceLeaseManager:
    """管理一个 worker 进程内的 CUDA 单卡训练租约。"""

    def __init__(self) -> None:
        """初始化租约管理器。"""

        self._condition = Condition()
        self._leased_cuda_indices: set[int] = set()

    def acquire(
        self,
        requested_device: str | None,
        *,
        torch_module: Any | None = None,
    ) -> TrainingDeviceLease:
        """为一次训练获取设备租约。

        规则：
        - `auto`：有空闲 CUDA 时分配第一张空闲卡，没有 CUDA 时使用 CPU。
        - `cuda` / `gpu`：分配第一张空闲 CUDA 卡，没有 CUDA 时直接报错。
        - `cuda:n`：等待指定 CUDA 卡空闲。
        - `cpu`：直接使用 CPU，不占用 CUDA 租约。
        """

        requested = (requested_device or "auto").strip()
        normalized = requested.lower()
        if normalized == "cpu":
            info = TrainingDeviceLeaseInfo(
                requested_device=requested_device,
                resolved_device="cpu",
                cuda_index=None,
                waited_seconds=0.0,
            )
            return TrainingDeviceLease(manager=self, info=info)

        cuda_available, cuda_count = _read_cuda_inventory(torch_module)
        if normalized in _AUTO_DEVICE_NAMES:
            if not cuda_available or cuda_count <= 0:
                info = TrainingDeviceLeaseInfo(
                    requested_device=requested_device,
                    resolved_device="cpu",
                    cuda_index=None,
                    waited_seconds=0.0,
                )
                return TrainingDeviceLease(manager=self, info=info)
            return self._acquire_first_free_cuda(
                requested_device=requested_device,
                cuda_count=cuda_count,
            )

        if normalized in _CUDA_AUTO_DEVICE_NAMES:
            _require_cuda(cuda_available=cuda_available, cuda_count=cuda_count)
            return self._acquire_first_free_cuda(
                requested_device=requested_device,
                cuda_count=cuda_count,
            )

        if normalized.startswith("cuda:"):
            _require_cuda(cuda_available=cuda_available, cuda_count=cuda_count)
            cuda_index = _parse_cuda_index(normalized, cuda_count=cuda_count)
            return self._acquire_specific_cuda(
                requested_device=requested_device,
                cuda_index=cuda_index,
            )

        raise InvalidRequestError(
            "不支持的训练设备名称",
            details={"device": requested_device},
        )

    def release(self, cuda_index: int | None) -> None:
        """释放指定 CUDA 设备索引。"""

        if cuda_index is None:
            return
        with self._condition:
            self._leased_cuda_indices.discard(cuda_index)
            self._condition.notify_all()

    def _acquire_first_free_cuda(
        self,
        *,
        requested_device: str | None,
        cuda_count: int,
    ) -> TrainingDeviceLease:
        """等待并分配第一张空闲 CUDA 卡。"""

        started_at = monotonic()
        with self._condition:
            while True:
                for cuda_index in range(cuda_count):
                    if cuda_index not in self._leased_cuda_indices:
                        self._leased_cuda_indices.add(cuda_index)
                        info = TrainingDeviceLeaseInfo(
                            requested_device=requested_device,
                            resolved_device=f"cuda:{cuda_index}",
                            cuda_index=cuda_index,
                            waited_seconds=monotonic() - started_at,
                        )
                        return TrainingDeviceLease(manager=self, info=info)
                self._condition.wait(timeout=1.0)

    def _acquire_specific_cuda(
        self,
        *,
        requested_device: str | None,
        cuda_index: int,
    ) -> TrainingDeviceLease:
        """等待并分配指定 CUDA 卡。"""

        started_at = monotonic()
        with self._condition:
            while cuda_index in self._leased_cuda_indices:
                self._condition.wait(timeout=1.0)
            self._leased_cuda_indices.add(cuda_index)
            info = TrainingDeviceLeaseInfo(
                requested_device=requested_device,
                resolved_device=f"cuda:{cuda_index}",
                cuda_index=cuda_index,
                waited_seconds=monotonic() - started_at,
            )
            return TrainingDeviceLease(manager=self, info=info)


_GLOBAL_TRAINING_DEVICE_LEASE_MANAGER = TrainingDeviceLeaseManager()


def acquire_training_device_lease(
    requested_device: str | None,
    *,
    torch_module: Any | None = None,
) -> TrainingDeviceLease:
    """使用全局训练设备租约管理器获取设备。"""

    return _GLOBAL_TRAINING_DEVICE_LEASE_MANAGER.acquire(
        requested_device,
        torch_module=torch_module,
    )


def _read_cuda_inventory(torch_module: Any | None) -> tuple[bool, int]:
    """读取当前 Python 环境可见的 CUDA 设备数量。"""

    torch = torch_module
    if torch is None:
        import torch as torch  # type: ignore[no-redef]

    cuda = getattr(torch, "cuda", None)
    if cuda is None:
        return False, 0
    is_available = getattr(cuda, "is_available", None)
    device_count = getattr(cuda, "device_count", None)
    available = bool(is_available()) if callable(is_available) else False
    count = int(device_count()) if callable(device_count) else 0
    return available, max(0, count)


def _require_cuda(*, cuda_available: bool, cuda_count: int) -> None:
    """确认当前环境存在可用 CUDA 设备。"""

    if not cuda_available or cuda_count <= 0:
        raise InvalidRequestError("当前运行环境没有可用 CUDA 设备，不能选择 CUDA 训练设备")


def _parse_cuda_index(device_name: str, *, cuda_count: int) -> int:
    """解析并校验 `cuda:n` 形式的设备索引。"""

    raw_index = device_name.split(":", 1)[1]
    try:
        cuda_index = int(raw_index)
    except ValueError as error:
        raise InvalidRequestError(
            "CUDA 训练设备索引必须是整数",
            details={"device": device_name},
        ) from error
    if cuda_index < 0 or cuda_index >= cuda_count:
        raise InvalidRequestError(
            "CUDA 训练设备索引超出当前设备范围",
            details={"device": device_name, "cuda_count": cuda_count},
        )
    return cuda_index


__all__ = [
    "TrainingDeviceLease",
    "TrainingDeviceLeaseInfo",
    "TrainingDeviceLeaseManager",
    "acquire_training_device_lease",
]
