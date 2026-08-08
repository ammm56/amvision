"""模型输入规格 API 公共 schema。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.service.domain.models.model_input_spec import (
    MAX_MODEL_INPUT_DIMENSION,
    SpatialSize,
)


class SpatialSizeRequest(BaseModel):
    """使用明确 width/height 字段接收模型空间尺寸。"""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0, le=MAX_MODEL_INPUT_DIMENSION, description="输入图片宽度")
    height: int = Field(gt=0, le=MAX_MODEL_INPUT_DIMENSION, description="输入图片高度")

    @model_validator(mode="after")
    def validate_pixel_count(self) -> "SpatialSizeRequest":
        """复用领域对象校验总像素上限。"""

        self.to_domain()
        return self

    def to_domain(self) -> SpatialSize:
        """转换为领域层 SpatialSize。"""

        return SpatialSize(width=self.width, height=self.height)

    @property
    def hw(self) -> tuple[int, int]:
        """返回应用层训练 core 使用的 ``(height, width)``。"""

        return self.to_domain().hw


class SpatialSizeResponse(BaseModel):
    """使用明确 width/height 字段返回模型空间尺寸。"""

    width: int = Field(gt=0, le=MAX_MODEL_INPUT_DIMENSION, description="输入图片宽度")
    height: int = Field(gt=0, le=MAX_MODEL_INPUT_DIMENSION, description="输入图片高度")

    @model_validator(mode="after")
    def validate_pixel_count(self) -> "SpatialSizeResponse":
        """防止把无界尺寸写回公开模型契约。"""

        SpatialSize(width=self.width, height=self.height)
        return self

    @classmethod
    def from_hw(cls, value: tuple[int, int]) -> "SpatialSizeResponse":
        """从内部 ``(height, width)`` 构造响应。"""

        return cls(height=int(value[0]), width=int(value[1]))
