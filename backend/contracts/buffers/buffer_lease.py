"""LocalBufferBroker buffer lease 合同。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


BUFFER_LEASE_FORMAT = "amvision.buffer-lease.v1"
BUFFER_LEASE_STATES = ("writing", "active", "released", "expired", "reclaimed")


class BufferLease(BaseModel):
    """描述 LocalBufferBroker 中一次短期 buffer 占用。

    字段：
    - format_id：当前 lease JSON 格式版本。
    - lease_id：本次租约 id。
    - buffer_id：租约占用的 buffer 槽位 id。
    - owner_kind：租约拥有者类型，例如 preview-run、workflow-runtime 或 deployment-worker。
    - owner_id：租约拥有者实例 id。
    - pool_name：所属 mmap pool 名称。
    - file_path：mmap 文件路径。
    - offset：租约在 mmap 文件中的起始偏移。
    - size：租约可读写的有效字节数。
    - created_at：租约创建时间。
    - expires_at：租约过期时间；为空表示由调用方显式释放。
    - ref_count：当前引用计数。
    - state：租约状态，支持 writing、active、released、expired 和 reclaimed。
    - trace_id：链路追踪 id。
    - broker_epoch：broker 启动代次，用于识别重启后的旧引用。
    - generation：槽位复用代次，用于识别释放后被复用的旧引用。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[BUFFER_LEASE_FORMAT] = BUFFER_LEASE_FORMAT
    lease_id: str
    buffer_id: str
    owner_kind: str
    owner_id: str
    pool_name: str
    file_path: str
    offset: int = Field(ge=0)
    size: int = Field(gt=0)
    created_at: datetime
    expires_at: datetime | None = None
    ref_count: int = Field(default=1, ge=0)
    state: Literal["writing", "active", "released", "expired", "reclaimed"] = "active"
    trace_id: str | None = None
    broker_epoch: str
    generation: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_lease(self) -> BufferLease:
        """校验 lease 字段的基础一致性。

        返回：
        - BufferLease：校验后的 lease。
        """

        _require_stripped_text(self.lease_id, "lease_id")
        _require_stripped_text(self.buffer_id, "buffer_id")
        _require_stripped_text(self.owner_kind, "owner_kind")
        _require_stripped_text(self.owner_id, "owner_id")
        _require_stripped_text(self.pool_name, "pool_name")
        _require_stripped_text(self.file_path, "file_path")
        _require_stripped_text(self.broker_epoch, "broker_epoch")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at 必须晚于 created_at")
        return self


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。

    参数：
    - value：待校验字符串。
    - field_name：字段名称。

    返回：
    - str：去除两端空白后的字符串。
    """

    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} 不能为空")
    return normalized_value