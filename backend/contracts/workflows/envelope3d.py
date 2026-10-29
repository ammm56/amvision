"""可见包络的栅格、目标与剖面参数；物理量沿已解析的评价面单位。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import Positive
from backend.contracts.workflows.metrology import Contract, Finite
from backend.contracts.workflows.point_cloud import JsonCount, PositiveCount

Point2 = tuple[Finite, Finite]
PROFILE_SIDES = ("u-min", "u-max", "v-min", "v-max")


class EnvelopeGrid(Contract):
    """有限格阵；origin 为左下格角，shape 按 U/V 排列，不从输入极值推断。"""

    origin: Point2
    step: Positive
    shape: tuple[PositiveCount, PositiveCount]
    min_cell_count: PositiveCount

    @model_validator(mode="after")
    def check_extent(self) -> Self:
        """浮点溢出或步长小于当前位置可表示间隔不能产生有效格阵。"""
        from math import isfinite

        for origin, count in zip(self.origin, self.shape):
            end = origin + count * self.step
            if not isfinite(end) or not origin < origin + self.step <= end:
                raise ValueError("可见包络栅格范围或步长不可表示")
        return self


class EnvelopeSelection(Contract):
    """种子窗口选择唯一连通目标；形态学仅改变归属，不制造观测格。"""

    seed_min: Point2
    seed_max: Point2
    connectivity: Literal[4, 8]
    closing_radius_cells: JsonCount

    @model_validator(mode="after")
    def check_seed(self) -> Self:
        """窗口必须有面积，不能用含义随采样变化的候选序号。"""
        if any(a >= b for a, b in zip(self.seed_min, self.seed_max)):
            raise ValueError("种子窗口必须严格递增")
        return self


class EnvelopeProfiles(Contract):
    """格边和格中心阈值插值是显式方法，不是严格截线失败后的回退。"""

    foreground: Literal["above", "below"]
    edge_policy: Literal["cell-edge", "interpolate-or-cell-edge"]
    min_observed_length: Positive


class VisibleEnvelopeSettings(Contract):
    """本次高度已由既有来源解析；内核使用截面相对高度零点。"""

    grid: EnvelopeGrid
    selection: EnvelopeSelection
    profiles: EnvelopeProfiles

    @model_validator(mode="after")
    def check_seed_grid(self) -> Self:
        """种子不得超出明确的测量窗口。"""
        g, s = self.grid, self.selection
        if any(
            low < origin or high > origin + count * g.step
            for low, high, origin, count in zip(
                s.seed_min, s.seed_max, g.origin, g.shape
            )
        ):
            raise ValueError("种子窗口必须位于栅格范围内")
        return self


class ProfileLayout(Contract):
    """四侧统计剖面的连接；breaks 指与前一站位断开的局部顶点号。"""

    side: Literal["u-min", "u-max", "v-min", "v-max"]
    breaks: tuple[PositiveCount, ...]

    @model_validator(mode="after")
    def check_breaks(self) -> Self:
        """断点必须严格递增；总数边界由所属段验证。"""
        if any(a >= b for a, b in zip(self.breaks, self.breaks[1:])):
            raise ValueError("剖面断点必须严格递增")
        return self


class RobustProfileSpans(Contract):
    """四侧独立分位范围；只有明确的剖面来源才能进入此方法。"""

    kind: Literal["robust-profile-spans"]
    lower_quantile: Annotated[Finite, Field(ge=0, lt=0.5)]
    upper_quantile: Annotated[Finite, Field(gt=0.5, le=1)]
    quantile_method: Literal["linear"]


class ProfileQuantileContact(Contract):
    """统计端点不是实测极值点，记录参与有序样本的逻辑行及系数。"""

    kind: Literal["profile-quantile"]
    side: Literal["u-min", "u-max", "v-min", "v-max"]
    sample_count: PositiveCount
    quantile: Annotated[Finite, Field(ge=0, le=1)]
    method: Literal["linear"]
    ranks: tuple[JsonCount, JsonCount]
    vertex_indices: tuple[JsonCount, JsonCount]
    weight: Annotated[Finite, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def check_ranks(self) -> Self:
        """秩和插值系数必须对应声明的线性分位定义。"""
        value = self.quantile * (self.sample_count - 1)
        first = int(value)
        last = min(first + 1, self.sample_count - 1)
        if self.ranks != (first, last) or abs(self.weight - (value - first)) > 1e-12:
            raise ValueError("分位端点秩或系数不一致")
        return self
