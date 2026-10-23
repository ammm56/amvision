"""M3.1 高度和高差参数；质量阈值显式配置，不允许支持域外推。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import (
    FitPlaneParameters,
    GeometryQualityPolicy,
    Point3,
    Positive,
    require_unit,
)
from backend.contracts.workflows.metrology import Contract, Finite, Identifier
from backend.contracts.workflows.point_cloud import LengthUnit


def distance_metric_units(unit: str) -> dict[str, str]:
    """双方支持使用同一组完整指标，不以总布尔值掩盖缺测。"""
    return {
        f"{side}_{name}": metric_unit
        for side in ("reference", "target")
        for name, metric_unit in (
            ("count", "1"),
            ("covered", "1"),
            ("direction_cosine", "1"),
            ("nearest_distance", unit),
            ("triangle_edge", unit),
            ("max_residual", unit),
        )
    }


def statistic_metric_units(unit: str) -> dict[str, str]:
    """统计差约束双方实际点数和总体标准差。"""
    return {
        f"{side}_{name}": metric_unit
        for side in ("reference", "target")
        for name, metric_unit in (("count", "1"), ("std", unit))
    }


def require_measurement_policy(policy, units, *, statistic=False):
    """校验策略完整性；实际上下限计算只调用现有比较器。"""
    rules = {r.item_id: r for r in policy.rules}
    if set(rules) != set(units):
        raise ValueError("测量质量必须完整配置本方法的指标")
    for name, rule in rules.items():
        if not rule.enabled or not rule.required or rule.unit != units[name]:
            raise ValueError("测量质量指标必须启用、必检且单位正确")
        if name.endswith("_count"):
            if rule.lower is None or rule.lower < (1 if statistic else 3):
                raise ValueError("测量支持数缺少合法下限")
        elif name.endswith("_covered"):
            if rule.lower != 1 or not rule.include_lower:
                raise ValueError("M3.1 必须要求交点位于实际支持域内")
        elif name.endswith("_cosine"):
            if rule.lower is None or not 0 < rule.lower <= 1:
                raise ValueError("测量方向必须明确非平行条件")
        elif rule.upper is None or rule.upper < 0:
            raise ValueError("距离、残差和离散程度必须明确非负上限")


class MeasurementIdentity(Contract):
    """每节点配置一个稳定量值；多位置复用 Workflow 的节点组合。"""

    item_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit


class DirectionalSettings(Contract):
    """同一测量直线及交点附近的有限支持搜索半径。"""

    query_position: Point3
    direction: Point3
    support_radius: Positive
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_direction(self) -> Self:
        """方向不可从相机朝向或源 Z 推测。"""
        require_unit(self.direction)
        return self


class HeightQueryParameters(MeasurementIdentity, DirectionalSettings):
    """有限圆柱内局部拟面；完整原精度数据重算，不从 Preview 取值。"""

    reference_feature_id: Identifier
    search_radius: Positive
    search_interval: tuple[Finite, Finite]
    plane_fit: FitPlaneParameters

    @model_validator(mode="after")
    def check_parameters(self) -> Self:
        """保留搜索方向/轴向窗口，拒绝倒置窗口及同名参考/目标。"""
        if self.search_interval[0] >= self.search_interval[1]:
            raise ValueError("高度搜索区间必须严格递增")
        if self.reference_feature_id == self.plane_fit.feature_id:
            raise ValueError("高度目标与参考特征 ID 不能相同")
        require_measurement_policy(
            self.quality_policy, distance_metric_units(self.length_unit)
        )
        return self


class DirectionalStep(DirectionalSettings):
    """两个既有平面在同一评价位置的有符号方向距离。"""

    kind: Literal["directional-planes"]
    reference_feature_id: Identifier
    target_feature_id: Identifier

    @model_validator(mode="after")
    def check_features(self) -> Self:
        """显式选择不同特征，不按输入顺序配对。"""
        if self.reference_feature_id == self.target_feature_id:
            raise ValueError("高差双方特征 ID 不能相同")
        return self


class MeanStatistic(Contract):
    """全支持点投影的算术均值。"""

    kind: Literal["mean"]


class MedianStatistic(Contract):
    """全支持点投影中位数，偶数样本取中间两项的均值。"""

    kind: Literal["median"]


class QuantileStatistic(Contract):
    """精确分位数；概率和 NumPy 方法均为显式配方参数。"""

    kind: Literal["quantile"]
    probability: Annotated[Finite, Field(ge=0, le=1)]
    method: Literal[
        "inverted_cdf",
        "averaged_inverted_cdf",
        "closest_observation",
        "interpolated_inverted_cdf",
        "hazen",
        "weibull",
        "linear",
        "median_unbiased",
        "normal_unbiased",
        "lower",
        "higher",
        "midpoint",
        "nearest",
    ]


class StatisticalStep(Contract):
    """两个已明确裁剪 ROI 的统计差，不虚构实际端点。"""

    kind: Literal["roi-statistic"]
    origin: Point3
    direction: Point3
    statistic: Annotated[
        MeanStatistic | MedianStatistic | QuantileStatistic, Field(discriminator="kind")
    ]
    quality_policy: GeometryQualityPolicy

    @model_validator(mode="after")
    def check_direction(self) -> Self:
        """统计投影沿同一显式单位方向。"""
        require_unit(self.direction)
        return self


class MeasureStepParameters(MeasurementIdentity):
    """两种测量定义互斥；切换模式必须提交完整新配置。"""

    mode: Annotated[DirectionalStep | StatisticalStep, Field(discriminator="kind")]

    @model_validator(mode="after")
    def check_policy(self) -> Self:
        """不能用另一模式的质量指标或单位放行当前测量。"""
        statistic = isinstance(self.mode, StatisticalStep)
        require_measurement_policy(
            self.mode.quality_policy,
            (statistic_metric_units if statistic else distance_metric_units)(
                self.length_unit
            ),
            statistic=statistic,
        )
        return self


class HeightNodeParameters(Contract):
    """高度配置与前端使用同一原子草稿。"""

    settings: HeightQueryParameters


class StepNodeParameters(Contract):
    """高差模式及其配置原子更新，不保留隐藏模式旧参数。"""

    settings: MeasureStepParameters
