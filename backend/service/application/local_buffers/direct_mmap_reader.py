"""LocalBufferBroker 引用的跨独立进程只读 mmap reader。"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any
import mmap

from backend.contracts.buffers import BufferRef, FrameRef
from backend.service.application.errors import InvalidRequestError
from backend.service.application.local_buffers.broker_settings import (
    LocalBufferBrokerSettings,
)


class DirectMmapLocalBufferReader:
    """在 deployment worker 内直接读取已授权的 mmap 文件区间。

    该 reader 不负责申请或释放 lease。调用方必须在同步推理返回前保持
    BufferRef/FrameRef 所属 owner 存活。它只接受配置中声明的 pool 文件，避免
    把外部构造的任意路径当作本地文件读取。
    """

    def __init__(self, settings: LocalBufferBrokerSettings | dict[str, Any]) -> None:
        """加载 broker pool 配置并建立允许访问的绝对路径索引。"""

        self.settings = (
            settings
            if isinstance(settings, LocalBufferBrokerSettings)
            else LocalBufferBrokerSettings.model_validate(settings)
        )
        root_dir = Path(self.settings.root_dir).resolve()
        self._pool_settings_by_path = {
            (root_dir / pool.pool_name / pool.file_name).resolve(): pool
            for pool in self.settings.pools
        }
        self._mapped_files: dict[Path, tuple[Any, mmap.mmap]] = {}
        self._lock = Lock()

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes | memoryview:
        """直接映射并读取普通 BufferRef 指向的有效区间。"""

        return self._read_ref_range(
            path=buffer_ref.path,
            offset=buffer_ref.offset,
            size=buffer_ref.size,
            reference_kind="buffer",
            media_type=buffer_ref.media_type,
        )

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes | memoryview:
        """直接映射并读取 FrameRef 指向的有效区间。"""

        return self._read_ref_range(
            path=frame_ref.path,
            offset=frame_ref.offset,
            size=frame_ref.size,
            reference_kind="frame",
            media_type=frame_ref.media_type,
        )

    def get_health_summary(self) -> dict[str, object]:
        """返回 deployment worker 可观测的 direct mmap reader 状态。"""

        return {
            "connected": True,
            "transport": "direct-readonly-mmap",
            "pool_count": len(self._pool_settings_by_path),
        }

    def close(self) -> None:
        """关闭缓存的只读 mmap view 和文件句柄。"""

        with self._lock:
            mapped_files = tuple(self._mapped_files.values())
            self._mapped_files.clear()
        for file, view in mapped_files:
            try:
                view.close()
            except BufferError:
                # worker 停止时仍有 NumPy view 的异常路径由进程退出统一回收。
                pass
            file.close()

    def _read_ref_range(
        self,
        *,
        path: str,
        offset: int,
        size: int,
        reference_kind: str,
        media_type: str,
    ) -> bytes | memoryview:
        """校验 pool、边界和槽位后读取引用区间。"""

        resolved_path = Path(path).resolve()
        pool = self._pool_settings_by_path.get(resolved_path)
        if pool is None:
            raise InvalidRequestError(
                "LocalBufferRef path 不属于已配置 mmap pool",
                details={
                    "path": str(resolved_path),
                    "reference_kind": reference_kind,
                },
            )
        if offset < 0 or size <= 0:
            raise InvalidRequestError(
                "LocalBufferRef 读取范围不合法",
                details={"offset": offset, "size": size},
            )
        slot_size = int(pool.slot_size_bytes)
        if offset % slot_size != 0 or size > slot_size:
            raise InvalidRequestError(
                "LocalBufferRef 与 mmap pool 槽位边界不一致",
                details={
                    "offset": offset,
                    "size": size,
                    "slot_size_bytes": slot_size,
                },
            )
        expected_size = slot_size * int(pool.slot_count)
        if offset + size > expected_size:
            raise InvalidRequestError(
                "LocalBufferRef 超出 mmap pool 配置范围",
                details={
                    "offset": offset,
                    "size": size,
                    "pool_size_bytes": expected_size,
                },
            )
        view = self._get_or_open_view(
            path=resolved_path,
            expected_size=expected_size,
            required_end=offset + size,
        )
        del media_type
        return memoryview(view)[offset : offset + size].toreadonly()

    def _get_or_open_view(
        self,
        *,
        path: Path,
        expected_size: int,
        required_end: int,
    ) -> mmap.mmap:
        """返回缓存的只读 mmap，并在首次访问时校验文件容量。"""

        with self._lock:
            mapped = self._mapped_files.get(path)
            if mapped is not None:
                return mapped[1]
            try:
                file = path.open("rb", buffering=0)
            except FileNotFoundError as error:
                raise InvalidRequestError(
                    "LocalBufferRef mmap 文件不存在",
                    details={"path": str(path)},
                ) from error
            actual_size = path.stat().st_size
            if actual_size < expected_size or required_end > actual_size:
                file.close()
                raise InvalidRequestError(
                    "LocalBufferRef 超出当前 mmap 文件范围",
                    details={
                        "path": str(path),
                        "actual_size": actual_size,
                        "required_end": required_end,
                    },
                )
            view = mmap.mmap(file.fileno(), length=0, access=mmap.ACCESS_READ)
            self._mapped_files[path] = (file, view)
            return view
