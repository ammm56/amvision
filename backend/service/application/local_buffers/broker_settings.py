"""LocalBufferBroker 固定 arena 运行配置。"""

from __future__ import annotations

import struct
import sys

from pydantic import BaseModel, Field, model_validator

from backend.service.infrastructure.local_buffers.buddy_allocator import (
    BuddyArenaGeometry,
)


_MIB = 1024 * 1024
_GIB = 1024 * _MIB


class LocalBufferBrokerSettings(BaseModel):
    """描述单 Broker owner、单固定容量图片 arena。"""

    enabled: bool = True
    root_dir: str = "./data/buffers"
    arena_id: str = "local-buffer-main"
    arena_size_bytes: int = 2 * _GIB
    min_block_size_bytes: int = _MIB
    max_allocation_bytes: int = _GIB
    huge_reserve_bytes: int = 0
    reader_guard_slots: int = Field(default=64, gt=0)
    flush_on_write: bool = False
    startup_timeout_seconds: float = Field(default=60.0, gt=0.0)
    takeover_existing_process: bool = True
    takeover_timeout_seconds: float = Field(default=10.0, gt=0.0, le=60.0)
    request_timeout_seconds: float = Field(default=5.0, gt=0.0)
    shutdown_timeout_seconds: float = Field(default=5.0, gt=0.0)
    expire_interval_seconds: float = Field(default=5.0, ge=0.0)
    revocation_grace_seconds: float = Field(default=5.0, gt=0.0)

    @model_validator(mode="before")
    @classmethod
    def reject_fixed_pool_fields(cls, data: object) -> object:
        """开发期协议原地升级后拒绝全部旧 pool/slot 配置。"""

        if isinstance(data, dict):
            obsolete = {
                "default_pool",
                "default_pool_name",
                "pools",
                "pool_name",
                "slot_size_bytes",
                "slot_count",
            }.intersection(data)
            if obsolete:
                raise ValueError(
                    "LocalBufferBroker 不再支持固定 pool/slot 字段: "
                    + ", ".join(sorted(obsolete))
                )
        return data

    @model_validator(mode="after")
    def validate_settings(self) -> LocalBufferBrokerSettings:
        """校验 64-bit 边界、稳定 arena id 与 buddy 几何。"""

        if struct.calcsize("P") != 8 or sys.maxsize <= 2**32:
            raise ValueError("LocalBufferBroker 只支持 64-bit 进程")
        self.root_dir = self.root_dir.strip()
        self.arena_id = self.arena_id.strip()
        if not self.root_dir:
            raise ValueError("LocalBufferBroker root_dir 不能为空")
        if not self.arena_id:
            raise ValueError("LocalBufferBroker arena_id 不能为空")
        BuddyArenaGeometry(
            arena_size_bytes=self.arena_size_bytes,
            min_block_size_bytes=self.min_block_size_bytes,
            max_allocation_bytes=self.max_allocation_bytes,
            huge_reserve_bytes=self.huge_reserve_bytes,
        )
        return self


def resolve_preview_reservation_length(
    request: object,
    settings: LocalBufferBrokerSettings,
) -> int:
    """按已暂存输入长度确定结果图片的有界连续预留长度。"""

    input_length = settings.min_block_size_bytes
    image_payload = getattr(request, "input_image_payload", None)
    if isinstance(image_payload, dict):
        for field_name in ("buffer_ref", "frame_ref"):
            ref = image_payload.get(field_name)
            if not isinstance(ref, dict):
                continue
            value = ref.get("content_length")
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                input_length = value
                break
    return min(
        settings.max_allocation_bytes,
        max(4 * _MIB, input_length * 2),
    )
