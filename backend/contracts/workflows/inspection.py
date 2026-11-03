"""产品判定与记录契约；几何有效性和执行状态不等于产品状态。"""

from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, JsonValue, StrictBool, model_validator

from backend.contracts.workflows.metrology import (
    Contract,
    Finite,
    Identifier,
    LimitRule,
    unique_ids,
)

DecisionState = Literal["ok", "ng", "invalid"]
Count = Annotated[int, Field(strict=True, ge=0, le=8192)]


class LimitCheckItem(Contract):
    """保存完整量值、配置与判定；无效值不能变成零或 NG。"""

    item_id: Identifier
    required: StrictBool
    state: DecisionState
    passed: StrictBool
    valid: StrictBool
    value: Finite | None
    unit: Identifier
    actual_unit: Identifier | None
    lower: Finite | None
    upper: Finite | None
    include_lower: StrictBool
    include_upper: StrictBool
    reason: Identifier | None

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        """复核配置和状态一致性，防止消费者接受伪造的放行摘要。"""
        rule = LimitRule.model_validate(
            self.model_dump(
                include={
                    "item_id",
                    "required",
                    "unit",
                    "lower",
                    "upper",
                    "include_lower",
                    "include_upper",
                }
            )
        )
        if not self.valid:
            if (
                self.value is not None
                or self.state != "invalid"
                or self.passed
                or self.reason is None
            ):
                raise ValueError("无效判定必须没有数值、不可放行且有原因")
            return self
        if self.value is None or self.actual_unit != self.unit:
            raise ValueError("有效判定需要正确单位的有限数值")
        expected_reason = rule.violation_reason(self.value)
        if (
            self.reason != expected_reason
            or self.state != ("ok" if expected_reason is None else "ng")
            or self.passed != (expected_reason is None)
        ):
            raise ValueError("逐项判定与数值或限值不一致")
        return self


class LimitCheckSummary(Contract):
    """完整必检集合的三态汇总，不接受旧二态摘要或字符串替代。"""

    format_id: Literal["amvision.limit-check.v1"]
    observation_id: Identifier
    state: DecisionState
    passed: StrictBool
    reason: (
        Literal["no_required_checks", "required_invalid", "required_out_of_limits"]
        | None
    )
    items: Annotated[tuple[LimitCheckItem, ...], Field(max_length=8192)]
    required_count: Count
    required_ok_count: Count
    required_ng_count: Count
    required_invalid_count: Count
    optional_count: Count

    @model_validator(mode="after")
    def check_summary(self) -> Self:
        """必检无效优先；可选项不更改必检结论或分母。"""
        unique_ids([item.item_id for item in self.items], "checks")
        required = [item for item in self.items if item.required]
        counts = {
            state: sum(item.state == state for item in required)
            for state in ("ok", "ng", "invalid")
        }
        if (
            self.required_count != len(required)
            or self.optional_count != len(self.items) - len(required)
            or self.required_ok_count != counts["ok"]
            or self.required_ng_count != counts["ng"]
            or self.required_invalid_count != counts["invalid"]
        ):
            raise ValueError("必检计数与逐项证据不一致")
        if not required:
            state, reason = "invalid", "no_required_checks"
        elif counts["invalid"]:
            state, reason = "invalid", "required_invalid"
        elif counts["ng"]:
            state, reason = "ng", "required_out_of_limits"
        else:
            state, reason = "ok", None
        if (
            self.state != state
            or self.reason != reason
            or self.passed != (state == "ok")
        ):
            raise ValueError("总判定与必检证据不一致")
        return self


class InspectionRecord(Contract):
    """通用结果记录，执行成功与产品放行分开；仅 OK 可放行。"""

    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {"properties": {"state": {"const": "ok"}, "passed": {"const": True}}},
                {"properties": {"state": {"const": "ng"}, "passed": {"const": False}}},
                {
                    "properties": {
                        "state": {"const": "invalid"},
                        "passed": {"const": False},
                        "reason": {"type": "string", "pattern": r"\S"},
                    },
                    "required": ["reason"],
                },
            ]
        }
    )

    format_id: Literal["amvision.result-record.v1"]
    state: DecisionState
    passed: StrictBool
    reason: Annotated[str, Field(strict=True, min_length=1)] | None = None
    metrics: JsonValue = None
    conditions: JsonValue = None
    metadata: dict[str, JsonValue] | None = None
    alarm: dict[str, JsonValue] | None = None
    image: dict[str, JsonValue] | None = None
    video: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def check_decision(self) -> Self:
        """拒绝状态和放行冲突；完整数值判定的状态不得被记录覆盖。"""
        if self.passed != (self.state == "ok"):
            raise ValueError("产品状态与放行值不一致")
        if self.state == "invalid" and (self.reason is None or not self.reason.strip()):
            raise ValueError("无法判定必须保留原因")
        if (
            isinstance(self.conditions, dict)
            and self.conditions.get("format_id") == "amvision.limit-check.v1"
        ):
            summary = LimitCheckSummary.model_validate(self.conditions)
            if self.state != summary.state or self.passed != summary.passed:
                raise ValueError("结果记录与完整判定证据不一致")
        return self
