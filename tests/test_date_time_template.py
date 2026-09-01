"""Workflow 节点通用日期时间模板测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, cast

import pytest

from backend.nodes import render_date_time_template
from backend.service.application.errors import InvalidRequestError


_CURRENT_TIME = datetime(
    2026,
    12,
    21,
    15,
    4,
    5,
    123_999,
    tzinfo=timezone.utc,
)


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{YYYYMMDDhh}", "2026122115"),
        ("{DDMMYYYY hhmmss}", "21122026 150405"),
        ("{Y}/{YY}/{YYY}/{YYYY}", "6/26/026/2026"),
        ("{M}/{MM}/{D}/{DDhh}/{hh}", "2/12/1/2115/15"),
        ("{m}/{mm}/{s}/{ss}", "4/04/5/05"),
        ("{S}/{SS}/{SSS}", "3/23/123"),
        (
            "saveimage-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.jpg",
            "saveimage-2026-12-21-15-04-05-123.jpg",
        ),
        (
            "partition/{YYYY/MM/DD}/{hh:mm:ss}",
            "partition/2026/12/21/15:04:05",
        ),
    ],
)
def test_render_date_time_template_supports_free_field_combinations(
    template: str,
    expected: str,
) -> None:
    """验证字段可以在一个或多个块中自由组合，并遵守明确宽度。"""

    assert (
        render_date_time_template(template, current_time=_CURRENT_TIME)
        == expected
    )


def test_render_date_time_template_resolves_context_and_time_with_one_snapshot() -> None:
    """验证上下文占位符和多个时间块共用同一时间点。"""

    assert render_date_time_template(
        "{application_id}/{YYYY}/{MM}/{DD}/{node_id}-{hhmmssSSS}",
        current_time=_CURRENT_TIME,
        context={
            "application_id": "workflow-app-1",
            "node_id": "save-image",
        },
    ) == "workflow-app-1/2026/12/21/save-image-150405123"


@pytest.mark.parametrize(
    "template",
    [
        "{}",
        "{YYYYY}",
        "{MMM}",
        "{DDD}",
        "{hhh}",
        "{mmm}",
        "{sss}",
        "{SSSS}",
        "{yyyy}",
        "{Q}",
        "prefix-{YYYY",
        "prefix-YYYY}",
    ],
)
def test_render_date_time_template_rejects_invalid_fields(template: str) -> None:
    """验证超宽字段、未知字段和不完整大括号都会明确失败。"""

    with pytest.raises(InvalidRequestError, match="日期时间模板不合法"):
        render_date_time_template(template, current_time=_CURRENT_TIME)


def test_render_date_time_template_reports_field_width_boundary() -> None:
    """验证非法字段宽度返回可审计的字段、实际宽度和上限。"""

    with pytest.raises(InvalidRequestError) as exc_info:
        render_date_time_template("{DDD}", current_time=_CURRENT_TIME)

    assert exc_info.value.details == {
        "template": "{DDD}",
        "reason": "字段 DDD 超过最大宽度 2",
        "expression": "DDD",
        "field": "D",
        "width": 3,
        "max_width": 2,
    }


def test_render_date_time_template_rejects_non_string_value() -> None:
    """验证通用入口不会隐式字符串化其他类型。"""

    with pytest.raises(InvalidRequestError, match="日期时间模板不合法"):
        render_date_time_template(20260901, current_time=_CURRENT_TIME)


def test_render_date_time_template_rejects_non_string_context_value() -> None:
    """验证节点不能通过上下文把非字符串值隐式写入模板。"""

    context = cast(Mapping[str, str], {"node_id": 1})

    with pytest.raises(InvalidRequestError) as exc_info:
        render_date_time_template(
            "{node_id}",
            current_time=_CURRENT_TIME,
            context=context,
        )

    assert exc_info.value.details["reason"] == "上下文占位符值必须是字符串"
