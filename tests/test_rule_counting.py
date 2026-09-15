"""独立分组计数契约测试。"""

import pytest

from backend.nodes.core_nodes.support.rule_counting import count_by_rules
from backend.service.application.errors import InvalidRequestError


def rules():
    """任意类别名，避免把模型类别固化到节点。"""
    return [
        {
            "key": "ok",
            "condition": {"operator": "in", "path": "label", "right": ["a", "b"]},
        },
        {
            "key": "ng",
            "condition": {"operator": "in", "path": "label", "right": ["c", "d"]},
        },
    ]


def test_independent_counts_and_explicit_fallback():
    """总数不决定 NG；兜底仅在明确配置时生效。"""
    items = (
        [{"label": "a"}] * 10
        + [{"label": "b"}] * 10
        + [{"label": "c"}, {"label": "d"}, {}, {"label": None}]
    )
    result = count_by_rules(items, rules())
    assert result == dict(
        counts={"ok": 20, "ng": 2},
        input_count=24,
        matched_count=22,
        fallback_count=0,
        unmatched_count=2,
    )
    assert count_by_rules(items, rules(), "ng")["counts"] == {"ok": 20, "ng": 4}
    assert count_by_rules([], rules())["counts"] == {"ok": 0, "ng": 0}


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{"key": "a", "condition": {"operator": "unknown"}}],
        [
            {
                "key": "a",
                "condition": {"operator": "and", "conditions": [{"operator": "in"}]},
            }
        ],
        rules() + [rules()[0]],
    ],
)
def test_invalid_rules_fail_even_without_items(bad):
    """空输入不能掩盖配置错误。"""
    with pytest.raises(InvalidRequestError):
        count_by_rules([], bad)


def test_overlapping_rules_fail():
    """顺序不能掩盖组冲突。"""
    conflicting = rules()
    conflicting[1]["condition"]["right"].append("a")
    with pytest.raises(InvalidRequestError, match="多个分组"):
        count_by_rules([{"label": "a"}], conflicting)
