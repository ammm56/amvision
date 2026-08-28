"""Inference daemon 对 backend 主 LocalBuffer 的只读依赖探测。"""

from __future__ import annotations

import contextlib
from pathlib import Path
from threading import Lock
from time import monotonic

from backend.service.application.local_buffers import (
    DirectMmapLocalBufferReader,
    LocalBufferBrokerSettings,
)
from backend.service.application.local_buffers.broker_instance_lock import (
    is_local_buffer_broker_instance_active,
)


class LocalBufferDependencyProbe:
    """确认 Broker owner 与主 arena layout 都已可供 daemon 使用。"""

    def __init__(
        self,
        *,
        buffers_root: str | Path,
        broker_settings: LocalBufferBrokerSettings,
        layout_validation_interval_seconds: float = 5.0,
    ) -> None:
        """绑定受信根目录、arena 几何和 layout 复核间隔。"""

        self.buffers_root = Path(buffers_root).resolve()
        self.broker_settings = broker_settings
        self.layout_validation_interval_seconds = max(
            0.1, float(layout_validation_interval_seconds)
        )
        self._lock = Lock()
        self._last_layout_validation_at = 0.0
        self._last_error: str | None = "尚未完成 LocalBuffer 依赖探测"

    def snapshot(self) -> dict[str, object]:
        """返回当前依赖快照；失败只报告状态，不创建或接管 Broker。"""

        with self._lock:
            now = monotonic()
            if not is_local_buffer_broker_instance_active(self.buffers_root):
                self._last_error = "backend LocalBufferBroker 尚未持有主数据面"
                return {
                    "ready": False,
                    "arena_id": self.broker_settings.arena_id,
                    "error": self._last_error,
                }
            if (
                self._last_layout_validation_at > 0.0
                and now - self._last_layout_validation_at
                < self.layout_validation_interval_seconds
            ):
                return {
                    "ready": True,
                    "arena_id": self.broker_settings.arena_id,
                    "error": None,
                }
            reader: DirectMmapLocalBufferReader | None = None
            try:
                reader = DirectMmapLocalBufferReader(
                    self.broker_settings,
                    root_dir=self.buffers_root,
                )
            except Exception as error:  # noqa: BLE001 - readiness 必须稳定降级
                self._last_error = str(error) or type(error).__name__
                return {
                    "ready": False,
                    "arena_id": self.broker_settings.arena_id,
                    "error": self._last_error,
                }
            finally:
                if reader is not None:
                    with contextlib.suppress(Exception):
                        reader.close()
            self._last_layout_validation_at = now
            self._last_error = None
            return {
                "ready": True,
                "arena_id": self.broker_settings.arena_id,
                "error": None,
            }
