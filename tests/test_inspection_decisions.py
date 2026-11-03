"""三态判定的完整真值、篡改拒绝和现有消费者回归。"""

from copy import deepcopy
from itertools import product

import pytest
from pydantic import ValidationError

from backend.contracts.workflows.inspection import LimitCheckSummary
from backend.contracts.workflows.metrology import LimitRule, NumericItem, NumericTable
from backend.nodes.core_nodes.io.output.records.result_record import (
    _result_record_handler,
)
from backend.nodes.core_nodes.support.batch_result_summary import (
    build_batch_result_summary,
)
from backend.nodes.core_nodes.support.inspection_record import (
    build_result_record_payload,
    require_result_record_payload,
)
from backend.nodes.core_nodes.support.measurement import check_limit_items, check_limits
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def decision(states, *, required=None):
    """由独立指定的量值状态生成真实比较器输入，不手填汇总。"""
    required = required if required is not None else [True] * len(states)
    items = tuple(
        NumericItem(
            item_id=f"item{index}",
            unit="millimeter",
            valid=state != "invalid",
            value={"ok": 1.0, "ng": 3.0, "invalid": None}[state],
            reason="missing_surface" if state == "invalid" else None,
        )
        for index, state in enumerate(states)
    )
    rules = tuple(
        LimitRule(
            item_id=item.item_id,
            unit="millimeter",
            lower=0.0,
            upper=2.0,
            required=is_required,
        )
        for item, is_required in zip(items, required)
    )
    return check_limits(NumericTable(observation_id="part1", items=items), rules)


@pytest.mark.parametrize("states", list(product(("ok", "ng", "invalid"), repeat=3)))
def test_required_truth_table(states):
    """必检无效优先，已有超差保留，只有全部有效且范围内才能放行。"""
    result = decision(states)
    expected = "invalid" if "invalid" in states else "ng" if "ng" in states else "ok"
    assert result["state"] == expected
    assert result["passed"] is (expected == "ok")
    assert [item["state"] for item in result["items"]] == list(states)
    assert result["required_count"] == 3
    for state in ("ok", "ng", "invalid"):
        assert result[f"required_{state}_count"] == states.count(state)
    assert (
        LimitCheckSummary.model_validate_json(
            LimitCheckSummary.model_validate(result).model_dump_json()
        ).model_dump(mode="json")
        == result
    )


@pytest.mark.parametrize("optional", ("ok", "ng", "invalid"))
def test_optional_does_not_change_required_result(optional):
    """可选项不改变必检结论或计数分母，无必检不能放行。"""
    result = decision(("ok", optional), required=(True, False))
    assert result["state"] == "ok"
    assert result["required_count"] == result["required_ok_count"] == 1
    assert result["optional_count"] == 1
    empty = decision((optional,), required=(False,))
    assert empty["state"] == "invalid" and empty["reason"] == "no_required_checks"
    assert decision(())["state"] == "invalid"


@pytest.mark.parametrize(
    "items,reason",
    [
        ((), "missing_value"),
        (
            (
                NumericItem(
                    item_id="d", unit="pixel", value=1.0, valid=True, reason=None
                ),
            ),
            "unit_mismatch",
        ),
        (
            (
                NumericItem(
                    item_id="d",
                    unit="millimeter",
                    value=None,
                    valid=False,
                    reason="no_edge",
                ),
            ),
            "no_edge",
        ),
    ],
)
def test_missing_and_wrong_unit_are_invalid(items, reason):
    """缺测和单位错误不能被归为可靠超差，也不能保留错误单位的数值。"""
    table = NumericTable(observation_id="part1", items=items)
    rules = (LimitRule(item_id="d", unit="millimeter", upper=2.0),)
    result = check_limits(table, rules)
    assert result["state"] == "invalid"
    assert result["items"][0]["reason"] == reason
    assert result["items"][0]["value"] is None
    assert {
        k: v for k, v in result["items"][0].items() if k != "state"
    } == check_limit_items(table, rules)[0]


@pytest.mark.parametrize(
    "key,value",
    [
        ("state", "ng"),
        ("passed", True),
        ("required_invalid_count", 0),
        ("optional_count", 7),
        ("reason", None),
        ("passed_count", 1),
        ("format_id", "amvision.limit-check.v2"),
    ],
)
def test_summary_rejects_inconsistent_fields(key, value):
    """下游不能信任篡改总状态或计数。"""
    summary = decision(("invalid", "ng"))
    summary[key] = value
    with pytest.raises(ValidationError):
        LimitCheckSummary.model_validate(summary)


@pytest.mark.parametrize("state", ("ok", "ng", "invalid"))
def test_record_preserves_complete_decision(state):
    """直接连接 Check Limits 摘要，记录保留观察身份、原因及 null。"""
    summary = decision((state,))
    output = _result_record_handler(
        WorkflowNodeExecutionRequest(
            node_id="record",
            node_definition=object(),
            parameters={},
            input_values={"decision": {"value": summary}},
            execution_metadata={},
        )
    )
    record = output["result"]
    assert record["state"] == state and record["passed"] is (state == "ok")
    assert record["conditions"] == summary
    assert require_result_record_payload(record) == record
    assert "ok_ng" not in record and "ok" not in record
    bad = deepcopy(record)
    bad["state"], bad["passed"] = "ng" if state == "ok" else "ok", state != "ok"
    with pytest.raises(InvalidRequestError):
        require_result_record_payload(bad)


def test_old_and_unknown_records_cannot_release():
    """开发阶段旧格式和冲突数据不走兼容分支。"""
    for record in (
        {"ok_ng": "OK", "ok": True},
        {"format_id": "amvision.result-record.v1", "state": "unknown", "passed": False},
        {"format_id": "amvision.result-record.v1", "state": "invalid", "passed": False},
    ):
        with pytest.raises(InvalidRequestError):
            require_result_record_payload(record)
    with pytest.raises(InvalidRequestError):
        _result_record_handler(
            WorkflowNodeExecutionRequest(
                node_id="record",
                node_definition=object(),
                parameters={},
                input_values={"decision": {"value": "OK"}},
                execution_metadata={},
            )
        )


def test_batch_keeps_invalid_unknown_and_denominator():
    """无法判定不混入 NG，未知数据仍占总体分母，不能虚增通过率。"""
    records = [
        build_result_record_payload(
            state=state, reason_value="missing" if state == "invalid" else None
        )
        for state in ("ok", "ng", "invalid")
    ]
    summary = build_batch_result_summary([*records, {"ok_ng": "OK", "ok": True}])
    assert (
        summary["ok_count"],
        summary["ng_count"],
        summary["invalid_count"],
        summary["unknown_count"],
    ) == (1, 1, 1, 1)
    assert summary["count"] == 4 and summary["pass_ratio"] == 0.25
    assert summary["has_invalid"] and not summary["all_ok"]
    assert "pass_ratio" not in build_batch_result_summary([])


@pytest.mark.parametrize(
    "key,value",
    [
        ("invalid_count", 0),
        ("count", 2),
        ("has_invalid", False),
        ("all_ok", True),
        ("pass_ratio", 0.5),
        ("alarm_count", 4),
        ("ok_count", True),
        ("format_id", "old-summary"),
    ],
)
def test_precomputed_batch_rejects_hidden_invalid_and_wrong_denominator(key, value):
    """已有批次摘要不重算时仍须复核所有状态、计数和分母。"""
    from backend.nodes.core_nodes.support.batch_result_summary import (
        require_batch_result_summary,
    )

    records = [
        build_result_record_payload(
            state=state, reason_value="missing" if state == "invalid" else None
        )
        for state in ("ok", "ng", "invalid")
    ]
    summary = build_batch_result_summary(records)
    assert require_batch_result_summary(summary) == summary
    summary[key] = value
    with pytest.raises(InvalidRequestError):
        require_batch_result_summary(summary)
