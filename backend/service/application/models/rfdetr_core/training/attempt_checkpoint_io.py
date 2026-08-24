"""RF-DETR Attempt 级 Lightning checkpoint 内存输出。"""

from __future__ import annotations

from io import BytesIO
from threading import Lock
from typing import Any

import torch
from lightning_fabric.plugins.io.checkpoint_io import CheckpointIO
from lightning_fabric.plugins.io.torch_io import TorchCheckpointIO


_MEMORY_PATH_PREFIX = "amvision-memory://"


class RfdetrAttemptCheckpointIO(CheckpointIO):
    """对内存目标编码完整 checkpoint，对普通路径委托标准 Torch IO。"""

    def __init__(self) -> None:
        self._delegate = TorchCheckpointIO()
        self._memory_payloads: dict[str, bytes] = {}
        self._lock = Lock()

    @staticmethod
    def build_memory_path(*, attempt_token: str, completed_epoch: int) -> str:
        """构造只在当前 Trainer 内有效的内存 checkpoint 目标。"""

        token = attempt_token.strip()
        if not token:
            raise ValueError("attempt_token 不能为空")
        return f"{_MEMORY_PATH_PREFIX}{token}/{int(completed_epoch)}"

    def save_checkpoint(
        self,
        checkpoint: dict[str, Any],
        path: str,
        storage_options: Any | None = None,
    ) -> None:
        """同步保存 checkpoint；内存路径不触碰临时目录或磁盘。"""

        normalized_path = str(path)
        if normalized_path.startswith(_MEMORY_PATH_PREFIX):
            if storage_options is not None:
                raise TypeError("内存 checkpoint 不支持 storage_options")
            buffer = BytesIO()
            torch.save(checkpoint, buffer)
            payload = buffer.getvalue()
            if not payload:
                raise RuntimeError("Lightning 生成了空 checkpoint")
            with self._lock:
                self._memory_payloads[normalized_path] = payload
            return
        self._delegate.save_checkpoint(
            checkpoint,
            normalized_path,
            storage_options=storage_options,
        )

    def load_checkpoint(
        self,
        path: str,
        storage_options: Any | None = None,
    ) -> dict[str, Any]:
        """读取普通持久 checkpoint；内存目标仅用于本次写后取 bytes。"""

        normalized_path = str(path)
        if normalized_path.startswith(_MEMORY_PATH_PREFIX):
            with self._lock:
                payload = self._memory_payloads.get(normalized_path)
            if payload is None:
                raise FileNotFoundError(normalized_path)
            return torch.load(BytesIO(payload), map_location="cpu", weights_only=False)
        return self._delegate.load_checkpoint(
            normalized_path,
            storage_options=storage_options,
        )

    def remove_checkpoint(self, path: str) -> None:
        """删除内存目标或委托删除普通路径。"""

        normalized_path = str(path)
        if normalized_path.startswith(_MEMORY_PATH_PREFIX):
            with self._lock:
                self._memory_payloads.pop(normalized_path, None)
            return
        self._delegate.remove_checkpoint(normalized_path)

    def pop_memory_checkpoint(self, path: str) -> bytes:
        """取得不可变 bytes 并立即释放临时内存目标。"""

        normalized_path = str(path)
        with self._lock:
            payload = self._memory_payloads.pop(normalized_path, None)
        if payload is None:
            raise RuntimeError("Lightning 未写入请求的内存 checkpoint")
        return payload


__all__ = ["RfdetrAttemptCheckpointIO"]
