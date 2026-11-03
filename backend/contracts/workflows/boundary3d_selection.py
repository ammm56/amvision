"""边界片段组的有限选区；配方目标身份与本次片段身份分开。"""

from math import pi
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import (
    CropCloudParameters,
    GeometryQualityPolicy,
    Positive,
)
from backend.contracts.workflows.metrology import Contract, Finite, Identifier


class BoundaryArcRegion(Contract):
    """评价面内有限环带与逆时针角区，角度为 rad，不跟随拟合圆心漂移。"""

    center: tuple[Finite, Finite]
    radius_range: tuple[Positive, Positive]
    start_angle: Annotated[Finite, Field(ge=0, lt=2 * pi)]
    sweep: Annotated[Positive, Field(le=2 * pi)]
    max_overlap_angle: Annotated[Finite, Field(ge=0, lt=pi)]

    @model_validator(mode="after")
    def check_region(self) -> Self:
        """环带必须有面积，容许重叠不能覆盖整个目标角区。"""
        if self.radius_range[0] >= self.radius_range[1]:
            raise ValueError("片段组半径范围必须严格递增")
        if self.max_overlap_angle >= self.sweep:
            raise ValueError("片段组重叠角必须小于目标扫角")
        return self


class BoundaryFragmentTarget(Contract):
    """同一目标的开弧片段集合；每段质量另行配置，不降低单段规则。"""

    group_id: Identifier
    region: CropCloudParameters
    arc: BoundaryArcRegion
    role: Literal["open"]
    fragment_quality_policy: GeometryQualityPolicy

    @property
    def target_id(self):
        """稳定目标组身份，不依赖候选段数量。"""
        return self.group_id

    @model_validator(mode="after")
    def check_quality(self) -> Self:
        """每片段必须明确至少两点及正长度，不隐式丢弃不满足的段。"""
        rules = {
            r.item_id: r
            for r in self.fragment_quality_policy.rules
            if r.enabled and r.required
        }
        count, length = rules.get("support_count"), rules.get("length")
        if (
            count is None
            or count.lower is None
            or count.lower < 2
            or length is None
            or length.lower is None
            or length.lower <= 0
        ):
            raise ValueError("片段质量必须明确支持点数及正长度下限")
        return self
