"""几何质量的逐项证据，复用现有数值与限值契约。"""

from typing import Annotated, Self
from pydantic import Field, StrictBool, model_validator
from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    NumericTable,
    unique_ids,
)


class GeometryCheck(Contract):
    """保留已有比较器的逐项证据，不从总 bool 反推缺测。"""

    item_id: Identifier
    required: StrictBool
    passed: StrictBool
    valid: StrictBool
    value: Finite | None
    unit: Identifier
    lower: Finite | None
    upper: Finite | None
    include_lower: StrictBool
    include_upper: StrictBool
    actual_unit: Identifier | None
    reason: Identifier | None

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        """拒绝缺值却声称有效、无原因却声称失败的外部摘要。"""
        if self.passed != (self.reason is None) or (self.passed and not self.valid):
            raise ValueError("几何逐项质量状态不一致")
        if self.valid and (self.value is None or self.actual_unit != self.unit):
            raise ValueError("有效几何指标缺少正确单位的数值")
        return self


class GeometryQuality(Contract):
    """指标与逐项规则证据；usable 只表示几何质量可用。"""

    metrics: NumericTable
    checks: Annotated[tuple[GeometryCheck, ...], Field(max_length=8192)]
    usable: StrictBool

    @model_validator(mode="after")
    def check_summary(self) -> Self:
        """摘要必须与完整的必检证据一致。"""
        unique_ids([item.item_id for item in self.checks], "checks")
        metrics = {item.item_id: item for item in self.metrics.items}
        for check in self.checks:
            metric = metrics.get(check.item_id)
            same_unit = metric is not None and metric.unit == check.unit
            if (
                check.actual_unit != (metric.unit if metric else None)
                or check.value != (metric.value if same_unit else None)
                or check.valid != (bool(same_unit) and metric.valid)
            ):
                raise ValueError("几何逐项证据与指标正文不一致")
        required = [item for item in self.checks if item.required]
        if self.usable != (
            bool(required) and all(item.valid and item.passed for item in required)
        ):
            raise ValueError("几何质量摘要与逐项证据不一致")
        return self


def check_geometry_policy(quality, policy) -> None:
    """只核对规则身份及参数；限值计算仍只在已有比较器执行。"""
    expected = [rule for rule in policy.rules if rule.enabled]
    if len(expected) != len(quality.checks):
        raise ValueError("几何质量检查数量与策略不一致")
    keys = (
        "item_id",
        "unit",
        "lower",
        "upper",
        "include_lower",
        "include_upper",
        "required",
    )
    for rule, check in zip(expected, quality.checks):
        if any(getattr(rule, key) != getattr(check, key) for key in keys):
            raise ValueError("几何质量检查与策略不一致")


def check_plane_metrics(quality: GeometryQuality, length_unit: str) -> None:
    """只校验指标物理范围和字段集合，不重复实现限值判断算法。"""
    metrics = {item.item_id: item for item in quality.metrics.items}
    units = dict(
        input_count="1",
        inlier_count="1",
        inlier_ratio="1",
        tangent_ratio="1",
        normal_gap="1",
        rms=length_unit,
        max_residual=length_unit,
    )
    if set(metrics) != set(units):
        raise ValueError("平面质量指标集合不完整")
    for name, item in metrics.items():
        if item.unit != units[name] or (item.valid and item.value < 0):
            raise ValueError("平面指标范围或单位不合法")
        if (
            item.valid
            and name in {"inlier_ratio", "tangent_ratio", "normal_gap"}
            and item.value > 1
        ):
            raise ValueError("平面比率必须位于 0 到 1")
        if item.valid and name.endswith("_count") and not item.value.is_integer():
            raise ValueError("平面计数必须为整数")
    total, count, ratio = (
        metrics[name] for name in ("input_count", "inlier_count", "inlier_ratio")
    )
    if total.valid != count.valid:
        raise ValueError("平面输入和支持计数有效性不一致")
    if total.valid and count.value > total.value:
        raise ValueError("平面支持计数超过输入计数")
    expected = count.value / total.value if total.valid and total.value else None
    if ratio.value != expected:
        raise ValueError("平面支持比例与计数不一致")


def check_frame_metrics(quality: GeometryQuality) -> None:
    """基准方向比率和条件数的结构范围，不代替配方质量阈值。"""
    metrics = {item.item_id: item for item in quality.metrics.items}
    if set(metrics) != {"axis_sine", "x_alignment", "z_alignment", "origin_condition"}:
        raise ValueError("基准质量指标集合不完整")
    for name, item in metrics.items():
        if item.unit != "1":
            raise ValueError("基准质量指标必须无量纲")
        if item.valid and (
            item.value < 1 if name == "origin_condition" else not 0 <= item.value <= 1
        ):
            raise ValueError("基准质量指标范围不合法")
