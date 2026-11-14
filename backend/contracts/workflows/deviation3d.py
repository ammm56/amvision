"""B17 基准偏差参数与摘要；逐点证据使用既有运行数组，不内嵌 JSON。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.measurement3d_parameters import (
    DirectionalPolicy,
    distance_metric_units,
    require_measurement_policy,
)
from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    NumericItem,
    NumericTable,
    unique_ids,
)
from backend.contracts.workflows.point_cloud import JsonCount, LengthUnit, Sha256

COMPONENTS = ("min", "max", "peak-to-valley", "mean", "rms")
DeviationComponent = Literal["min", "max", "peak-to-valley", "mean", "rms"]


class DeviationOutput(Contract):
    """每个统计量有独立量值 ID，不允许关闭其中一项来掩盖缺测。"""

    component: DeviationComponent
    item_id: Identifier


class DeviationParameters(DirectionalPolicy):
    """显式目标在上游选择，正方向只来自现有基准平面法向。"""

    reference_feature_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit
    outputs: Annotated[tuple[DeviationOutput, ...], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def check_parameters(self) -> Self:
        """支持条件沿用方向测量；五项必须完整且 ID 唯一。"""
        if {o.component for o in self.outputs} != set(COMPONENTS):
            raise ValueError("基准偏差必须完整配置五项统计")
        unique_ids([o.item_id for o in self.outputs], "outputs")
        require_measurement_policy(
            self.quality_policy,
            {
                k: v
                for k, v in distance_metric_units(self.length_unit).items()
                if k.startswith("reference_")
            },
        )
        return self


class DeviationExtreme(Contract):
    """并列极值显示代表按原行号再按逻辑行号选择，不声称唯一位置。"""

    logical_index: JsonCount
    source_index: JsonCount
    tie_count: Annotated[JsonCount, Field(gt=0)]


class DeviationStatistics(Contract):
    """全部可计算目标点的等权统计，RMS 不去均值，不删除失败支持点。"""

    count: Annotated[JsonCount, Field(gt=0)]
    minimum: Finite
    maximum: Finite
    peak_to_valley: Annotated[Finite, Field(ge=0)]
    mean: Finite
    rms: Annotated[Finite, Field(ge=0)]
    minimum_source: DeviationExtreme
    maximum_source: DeviationExtreme

    @model_validator(mode="after")
    def check_statistics(self) -> Self:
        """拒绝错序、伪造峰谷和超出统计规模的并列数。"""
        if (
            self.minimum > self.maximum
            or self.peak_to_valley != self.maximum - self.minimum
        ):
            raise ValueError("偏差极值或峰谷不一致")
        if not self.minimum <= self.mean <= self.maximum:
            raise ValueError("偏差均值超出极值范围")
        if any(
            s.tie_count > self.count for s in (self.minimum_source, self.maximum_source)
        ):
            raise ValueError("偏差极值并列数超出统计数量")
        return self


class DeviationCounts(Contract):
    """互斥终态完整覆盖目标；计数不是产品 OK/NG 判定。"""

    covered: JsonCount
    extended: JsonCount
    invalid_target: JsonCount
    invalid_reference: JsonCount
    outside_support: JsonCount
    support_quality_failed: JsonCount
    extension_limit_exceeded: JsonCount

    @property
    def total(self):
        """每行恰有一个终态。"""
        return sum(getattr(self, key) for key in type(self).model_fields)

    @property
    def failed(self):
        """支持不通过不能靠统计排除。"""
        return self.total - self.covered - self.extended


class DeviationSummary(Contract):
    """完整目标摘要，供公开量值、显示及显式保存读取共用。"""

    observation_id: Identifier
    parameters: DeviationParameters
    parameters_sha256: Sha256
    target_state: Literal["ready", "unavailable"]
    target_reason: Identifier | None
    target_count: JsonCount
    source_point_count: JsonCount
    reference_valid: StrictBool
    reference_reason: Identifier | None
    counts: DeviationCounts
    valid: StrictBool
    reason: (
        Literal[
            "target_unavailable",
            "empty_target",
            "reference_unavailable",
            "target_support_failed",
        ]
        | None
    )
    diagnostic: DeviationStatistics | None
    diagnostic_only: StrictBool

    @model_validator(mode="after")
    def check_summary(self) -> Self:
        """五项共用完整目标结论；不能将诊断统计冒充正式有效值。"""
        if self.parameters_sha256 != parameter_digest(self.parameters):
            raise ValueError("偏差参数摘要不一致")
        if self.counts.total != self.target_count:
            raise ValueError("偏差计数未覆盖完整目标")
        if (self.target_state == "ready") != (self.target_reason is None):
            raise ValueError("偏差目标可用状态与原因不一致")
        if self.target_state == "unavailable" and (
            self.target_count or self.source_point_count
        ):
            raise ValueError("不可用目标不能携带伪造点数")
        if self.reference_valid != (self.reference_reason is None):
            raise ValueError("偏差基准状态与原因不一致")
        valid = (
            self.target_count > 0 and self.reference_valid and self.counts.failed == 0
        )
        reason = (
            "target_unavailable"
            if self.target_state == "unavailable"
            else "empty_target"
            if not self.target_count
            else "reference_unavailable"
            if not self.reference_valid
            else "target_support_failed"
            if self.counts.failed
            else None
        )
        if (
            self.valid != valid
            or self.reason != reason
            or self.diagnostic_only != (not valid)
        ):
            raise ValueError("偏差总有效性与完整目标不一致")
        if not self.reference_valid and (
            self.diagnostic is not None or self.counts.covered or self.counts.extended
        ):
            raise ValueError("无效基准不能生成偏差统计或有效支持")
        if self.reference_valid and self.counts.invalid_reference:
            raise ValueError("有效基准不能携带基准无效行")
        if (
            not self.reference_valid
            and self.counts.invalid_target + self.counts.invalid_reference
            != self.target_count
        ):
            raise ValueError("无效基准的逐点终态不一致")
        computable = (
            self.target_count - self.counts.invalid_target
            if self.reference_valid
            else 0
        )
        if (self.diagnostic.count if self.diagnostic else 0) != computable:
            raise ValueError("偏差诊断没有包含全部可计算目标")
        if valid and (
            self.diagnostic is None or self.diagnostic.count != self.target_count
        ):
            raise ValueError("有效偏差缺少完整目标统计")
        if self.diagnostic is not None:
            if self.diagnostic.count > self.target_count:
                raise ValueError("偏差统计数量超出目标")
            for extreme in (
                self.diagnostic.minimum_source,
                self.diagnostic.maximum_source,
            ):
                if (
                    extreme.logical_index >= self.target_count
                    or extreme.source_index >= self.source_point_count
                ):
                    raise ValueError("偏差极值来源越界")
        return self

    def numeric_table(self) -> NumericTable:
        """正式量值由同一摘要生成，失败时保留五项身份且数值全部为 null。"""
        fields = dict(
            zip(COMPONENTS, ("minimum", "maximum", "peak_to_valley", "mean", "rms"))
        )
        return NumericTable(
            observation_id=self.observation_id,
            items=tuple(
                NumericItem(
                    item_id=o.item_id,
                    unit=self.parameters.length_unit,
                    value=getattr(self.diagnostic, fields[o.component])
                    if self.valid
                    else None,
                    valid=self.valid,
                    reason=self.reason,
                )
                for o in self.parameters.outputs
            ),
        )
