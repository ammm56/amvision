"""显式稳健拟圆权重与有界求解证据，不生成替代观测点。"""

from math import pi
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import Positive
from backend.contracts.workflows.metrology import Contract, Finite
from backend.contracts.workflows.point_cloud import JsonCount, Sha256


class RobustCircleFit(Contract):
    """显式选择角区均衡或连续边长权重；角域始终用于完整支持质量检查。"""

    kind: Literal["angular-soft-l1", "arc-length-soft-l1"]
    center: tuple[Finite, Finite]
    start_angle: Annotated[Finite, Field(ge=0, lt=2 * pi)]
    sweep: Annotated[Positive, Field(le=2 * pi)]
    sector_count: Annotated[int, Field(strict=True, ge=1, le=8192)]
    loss_scale: Positive
    inlier_residual: Positive


class CircleWeightEvidence(Contract):
    """保留完整候选摘要和逐角区计数，不往结果对象复制全部支持数组。"""

    candidate_count: JsonCount
    inlier_count: JsonCount
    sector_counts: Annotated[
        tuple[JsonCount, ...], Field(min_length=1, max_length=8192)
    ]
    sector_inliers: Annotated[
        tuple[JsonCount, ...], Field(min_length=1, max_length=8192)
    ]
    residuals_sha256: Sha256
    weights_sha256: Sha256

    @model_validator(mode="after")
    def check_counts(self) -> Self:
        """未占用角区不能产生支持，内点统计与完整候选严格对应。"""
        if (
            len(self.sector_counts) != len(self.sector_inliers)
            or sum(self.sector_counts) != self.candidate_count
            or sum(self.sector_inliers) != self.inlier_count
            or any(a < b for a, b in zip(self.sector_counts, self.sector_inliers))
        ):
            raise ValueError("拟圆角区与支持计数不一致")
        return self


class AngularSpan(Contract):
    """实际相邻边贡献的角区并集之一；不跨缺口推断覆盖。"""

    start_angle: Annotated[Finite, Field(ge=0, lt=2 * pi)]
    sweep: Annotated[Positive, Field(le=2 * pi)]

    @model_validator(mode="after")
    def check_end(self) -> Self:
        """跨零区间必须拆开，防止显示与覆盖采取不同解释。"""
        if self.start_angle + self.sweep > 2 * pi + 1e-14:
            raise ValueError("角支持区间跨越规范终点")
        return self
