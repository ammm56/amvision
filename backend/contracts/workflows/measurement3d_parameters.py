"""高度和高差参数；基准有限延伸显式配置，被测面必须实测支持。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.geometry3d import (
    FitPlaneParameters,
    GeometryQualityPolicy,
    Point3,
    Positive,
    require_unit,
)
from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    LimitRule,
)
from backend.contracts.workflows.point_cloud import LengthUnit
from backend.contracts.workflows.measurement3d_query import (
    MeasurementQuery,
    PoseUvQuery,
    QueryLine,
)


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


class MeasuredReference(Contract):
    """基准交点必须有满足原质量条件的实际支持。"""

    kind: Literal["measured-support"]


class ExtendedReference(Contract):
    """只延伸有效基准平面，距离上限来自配方而不是默认值。"""

    kind: Literal["plane-extension"]
    max_extension_distance: Positive


class DirectionalPolicy(Contract):
    """解析测量线前后保持不变的支持和质量策略。"""

    support_radius: Positive
    quality_policy: GeometryQualityPolicy
    reference_policy: Annotated[
        MeasuredReference | ExtendedReference, Field(discriminator="kind")
    ]


class DirectionalSettings(DirectionalPolicy):
    """同一测量线的显式来源。"""

    query: MeasurementQuery


class DirectionalEvaluation(DirectionalPolicy, QueryLine):
    """数值内核只消费成功解析的测量线及原策略。"""

    @classmethod
    def from_settings(cls, settings, line: QueryLine) -> Self:
        """不修改或回写配方，不覆盖任何质量限值。"""
        return cls(
            query_position=line.query_position,
            direction=line.direction,
            support_radius=settings.support_radius,
            reference_policy=settings.reference_policy,
            quality_policy=settings.quality_policy,
        )


def directional_quality_policy(settings, length_unit: str, *, extension: bool):
    """同一规则比较器按证据路径核验；不把不存在的实测三角形标为通过。"""
    if not extension:
        return settings.quality_policy
    if not isinstance(settings.reference_policy, ExtendedReference):
        raise ValueError("配方未允许基准延伸")
    rules = tuple(
        rule
        for rule in settings.quality_policy.rules
        if rule.item_id.startswith("target_")
        or rule.item_id == "reference_direction_cosine"
    ) + (
        LimitRule(
            item_id="reference_extension_distance",
            unit=length_unit,
            upper=settings.reference_policy.max_extension_distance,
        ),
    )
    return settings.quality_policy.model_copy(update={"rules": rules})


def directional_metric_units(unit: str, *, extension: bool):
    """指标集合与上方适用规则保持一致，所有读取方共用。"""
    units = distance_metric_units(unit)
    if extension:
        units = {
            name: value
            for name, value in units.items()
            if name.startswith("target_") or name == "reference_direction_cosine"
        }
        units["reference_extension_distance"] = unit
    return units


class HeightQueryParameters(MeasurementIdentity, DirectionalSettings):
    """有限圆柱内局部拟面；完整原精度数据重算，不从 Preview 取值。"""

    reference_feature_id: Identifier
    search_radius: Positive
    search_interval: tuple[Finite, Finite]
    plane_fit: FitPlaneParameters

    @model_validator(mode="after")
    def check_parameters(self) -> Self:
        """保留搜索方向/轴向窗口，拒绝倒置窗口及同名参考/目标。"""
        if (
            isinstance(self.query, PoseUvQuery)
            and self.query.target_frame_id == self.frame_id
        ):
            raise ValueError("查询目标坐标系不能与源坐标系相同")
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
        if (
            not statistic
            and isinstance(self.mode.query, PoseUvQuery)
            and self.mode.query.target_frame_id == self.frame_id
        ):
            raise ValueError("查询目标坐标系不能与源坐标系相同")
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
