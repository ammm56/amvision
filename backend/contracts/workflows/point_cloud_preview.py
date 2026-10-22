"""M1 三维显示参数，显示抽样不参与正式量测。"""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from pydantic import Field, model_validator
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import PositiveCount, JsonCount

CLOUD_PREVIEW_FAILURE_REASONS = frozenset(
    {"preview_size_limit", "preview_allocation_failed"}
)

DecimalText = Annotated[
    str,
    Field(
        strict=True,
        max_length=128,
        pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$",
    ),
]


class FiniteRange(Contract):
    """从实际显示样本的有限值计算色标。"""

    mode: Literal["finite-range"]


class FixedRange(Contract):
    """精确十进制边界，不将 uint64 经浮点 JSON 往返。"""

    mode: Literal["fixed"]
    min: DecimalText
    max: DecimalText

    @model_validator(mode="after")
    def check_order(self):
        """解析有限十进制，不接受退化或倒置范围。"""
        try:
            low, high = Decimal(self.min), Decimal(self.max)
        except InvalidOperation as error:
            raise ValueError("色标不是可表达的十进制数值") from error
        if not low.is_finite() or not high.is_finite() or low >= high:
            raise ValueError("色标范围必须有限且 min < max")
        return self


class SolidColor(Contract):
    """显示统一颜色。"""

    mode: Literal["solid"]


class RgbColor(Contract):
    """使用声明的原始 RGB 字节。"""

    mode: Literal["rgb"]


class ScalarColor(Contract):
    """按显式字段、分量和范围着色，不自动换字段。"""

    mode: Literal["scalar"]
    field: Identifier
    component: JsonCount
    range: Annotated[FiniteRange | FixedRange, Field(discriminator="mode")]


class CloudPreviewOptions(Contract):
    """节点显示参数；容量由运行策略另行约束。"""

    point_limit: PositiveCount
    color: Annotated[SolidColor | RgbColor | ScalarColor, Field(discriminator="mode")]
