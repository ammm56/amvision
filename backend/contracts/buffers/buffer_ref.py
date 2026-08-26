"""LocalBuffer 固定 arena 普通图片引用规则。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


BUFFER_REF_FORMAT = "amvision.buffer-ref.v1"


class BufferRef(BaseModel):
    """描述固定 arena 中一个短期连续 extent 的只读引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[BUFFER_REF_FORMAT] = BUFFER_REF_FORMAT
    buffer_id: str
    lease_id: str
    arena_id: str
    descriptor_index: int = Field(ge=0)
    descriptor_generation: int = Field(ge=1)
    broker_epoch: str
    offset: int = Field(ge=0)
    content_length: int = Field(gt=0)
    allocation_capacity_bytes: int = Field(gt=0)
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None
    media_type: str
    readonly: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ref(self) -> BufferRef:
        """校验 locator、连续范围和图片表示元数据。"""

        for field_name in (
            "buffer_id",
            "lease_id",
            "arena_id",
            "broker_epoch",
            "media_type",
        ):
            _require_stripped_text(getattr(self, field_name), field_name)
        if self.content_length > self.allocation_capacity_bytes:
            raise ValueError("content_length 不能超过 allocation_capacity_bytes")
        if any(dimension <= 0 for dimension in self.shape):
            raise ValueError("shape 中的维度必须为正整数")
        return self


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} 不能为空")
    return normalized_value
