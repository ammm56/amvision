"""LocalBuffer 服务端私有 owner handoff receipt 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.buffers.buffer_lease import BufferLease


LEASE_OWNERSHIP_RECEIPT_FORMAT = "amvision.local-buffer-ownership-receipt.v1"


class LeaseOwnershipReceipt(BaseModel):
    """保存条件 transfer/release 所需的完整 arena lease identity。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[LEASE_OWNERSHIP_RECEIPT_FORMAT] = (
        LEASE_OWNERSHIP_RECEIPT_FORMAT
    )
    arena_id: str
    descriptor_index: int = Field(ge=0)
    descriptor_generation: int = Field(ge=1)
    broker_epoch: str
    lease_id: str
    buffer_id: str
    lease_token: str
    owner_token: str
    owner_kind: str
    owner_id: str
    deadline_ns: int = Field(gt=0)
    offset: int = Field(ge=0)
    content_length: int = Field(gt=0)
    allocation_capacity_bytes: int = Field(gt=0)
    layout_fingerprint: str
    guard_path: str
    publication_guard_offset: int = Field(ge=0)
    writer_guard_offset: int = Field(ge=0)
    reader_guard_offset: int = Field(ge=0)
    reader_guard_slots: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_fields(self) -> LeaseOwnershipReceipt:
        """拒绝空 identity、无效 token 或越界 extent。"""

        for field_name in (
            "arena_id",
            "broker_epoch",
            "lease_id",
            "buffer_id",
            "lease_token",
            "owner_token",
            "owner_kind",
            "owner_id",
            "layout_fingerprint",
            "guard_path",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 不能为空")
        if len(self.lease_token) != 32 or len(self.owner_token) != 32:
            raise ValueError("lease_token 和 owner_token 必须是 128-bit hex")
        if self.content_length > self.allocation_capacity_bytes:
            raise ValueError("content_length 不能超过 allocation_capacity_bytes")
        return self


class ExternalBufferAllocation(BaseModel):
    """描述 backend 为外部 writer 准备的精确长度连续 extent。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lease: BufferLease
    receipt: LeaseOwnershipReceipt
    allocation_capacity_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_capacity(self) -> ExternalBufferAllocation:
        """保证公开 lease、私有 receipt 和分配容量一致。"""

        if self.lease.allocation_capacity_bytes != self.allocation_capacity_bytes:
            raise ValueError("allocation_capacity_bytes 与 lease 不一致")
        if self.receipt.allocation_capacity_bytes != self.allocation_capacity_bytes:
            raise ValueError("allocation_capacity_bytes 与 receipt 不一致")
        return self
