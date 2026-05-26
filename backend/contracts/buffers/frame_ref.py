"""LocalBufferBroker ring buffer 帧引用合同。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FRAME_REF_FORMAT = "amvision.frame-ref.v1"


class FrameRef(BaseModel):
    """描述 ring buffer channel 中某一帧的短期引用。

    字段：
    - format_id：当前引用 JSON 格式版本。
    - stream_id：连续帧来源 id。
    - sequence_id：帧递增序号。
    - buffer_id：ring buffer 槽位 id。
    - path：ring buffer mmap 文件路径；仅本机短期有效。
    - offset：帧数据在 mmap 文件中的起始偏移。
    - size：当前帧的有效字节数。
    - shape：raw 图像或 tensor 的形状。
    - dtype：raw 数据类型，例如 uint8。
    - layout：raw 数据布局，例如 HWC 或 CHW。
    - pixel_format：像素格式，例如 BGR 或 RGB。
    - media_type：媒体类型，例如 image/raw。
    - broker_epoch：broker 启动代次，用于识别重启后的旧引用。
    - generation：槽位复用代次，用于识别覆盖后的旧引用。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal["amvision.frame-ref.v1"] = FRAME_REF_FORMAT
    stream_id: str
    sequence_id: int = Field(ge=0)
    buffer_id: str
    path: str
    offset: int = Field(ge=0)
    size: int = Field(gt=0)
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None
    media_type: str
    broker_epoch: str
    generation: int = Field(ge=1)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ref(self) -> FrameRef:
        """校验 FrameRef 字段的基础一致性。

        返回：
        - FrameRef：校验后的引用。
        """

        _require_stripped_text(self.stream_id, "stream_id")
        _require_stripped_text(self.buffer_id, "buffer_id")
        _require_stripped_text(self.path, "path")
        _require_stripped_text(self.media_type, "media_type")
        _require_stripped_text(self.broker_epoch, "broker_epoch")
        if any(dimension <= 0 for dimension in self.shape):
            raise ValueError("shape 中的维度必须为正整数")
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