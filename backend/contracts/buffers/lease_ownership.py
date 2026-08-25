"""LocalBuffer 服务端私有 owner handoff receipt 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.buffers.buffer_lease import BufferLease


LEASE_OWNERSHIP_RECEIPT_FORMAT = "amvision.local-buffer-ownership-receipt.v1"


class LeaseOwnershipReceipt(BaseModel):
    """保存服务端条件 transfer/release 所需的完整 lease identity。

    该 receipt 是 backend 内部契约，不写入公开 ``BufferRef.v1``。SDK 只接收
    定位和 writer/reader guard 所需字段，不能据此直接修改 owner。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[LEASE_OWNERSHIP_RECEIPT_FORMAT] = (
        LEASE_OWNERSHIP_RECEIPT_FORMAT
    )
    pool_name: str
    lease_id: str
    buffer_id: str
    broker_epoch: str
    generation: int = Field(ge=1)
    owner_kind: str
    owner_id: str
    deadline_ns: int = Field(gt=0)
    writer_guard_path: str
    reader_guard_path: str
    reader_guard_slots: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_text_fields(self) -> LeaseOwnershipReceipt:
        """拒绝空 identity 或 guard path。"""

        for field_name in (
            "pool_name",
            "lease_id",
            "buffer_id",
            "broker_epoch",
            "owner_kind",
            "owner_id",
            "writer_guard_path",
            "reader_guard_path",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 不能为空")
        return self


class ExternalBufferAllocation(BaseModel):
    """描述 backend 为外部 writer 准备的精确长度 LocalBuffer 槽位。"""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    lease: BufferLease
    receipt: LeaseOwnershipReceipt
    slot_capacity_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_slot_capacity(self) -> ExternalBufferAllocation:
        """保证外部 writer 的固定映射范围覆盖本次有效内容。"""

        if self.lease.size > self.slot_capacity_bytes:
            raise ValueError("slot_capacity_bytes 不能小于 lease.size")
        return self
