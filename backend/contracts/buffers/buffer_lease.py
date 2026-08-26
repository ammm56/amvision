"""LocalBuffer 固定 arena lease 规则。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


BUFFER_LEASE_FORMAT = "amvision.buffer-lease.v1"
BUFFER_LEASE_STATES = (
    "writing",
    "active",
    "frame_reserved",
    "revoking",
    "quarantined",
    "released",
    "expired",
    "reclaimed",
)


class BufferLease(BaseModel):
    """描述固定 arena 中一次短期连续 extent 占用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[BUFFER_LEASE_FORMAT] = BUFFER_LEASE_FORMAT
    lease_id: str
    buffer_id: str
    owner_kind: str
    owner_id: str
    arena_id: str
    descriptor_index: int = Field(ge=0)
    descriptor_generation: int = Field(ge=1)
    broker_epoch: str
    offset: int = Field(ge=0)
    content_length: int = Field(gt=0)
    allocation_capacity_bytes: int = Field(gt=0)
    created_at: datetime
    expires_at: datetime | None = None
    ref_count: int = Field(default=1, ge=0)
    state: Literal[
        "writing",
        "active",
        "frame_reserved",
        "revoking",
        "quarantined",
        "released",
        "expired",
        "reclaimed",
    ] = "active"
    trace_id: str | None = None

    @model_validator(mode="after")
    def validate_lease(self) -> BufferLease:
        """校验 lease identity、extent 和时间边界。"""

        for field_name in (
            "lease_id",
            "buffer_id",
            "owner_kind",
            "owner_id",
            "arena_id",
            "broker_epoch",
        ):
            _require_stripped_text(getattr(self, field_name), field_name)
        if self.content_length > self.allocation_capacity_bytes:
            raise ValueError("content_length 不能超过 allocation_capacity_bytes")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at 必须晚于 created_at")
        return self


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} 不能为空")
    return normalized_value
