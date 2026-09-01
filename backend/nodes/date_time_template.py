"""Workflow 节点通用日期时间模板解析。"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Mapping

from backend.service.application.errors import InvalidRequestError


_DATE_TIME_BLOCK_PATTERN = re.compile(r"\{([^{}]*)\}")
_FIELD_MAX_WIDTHS = {
    "Y": 4,
    "M": 2,
    "D": 2,
    "h": 2,
    "m": 2,
    "s": 2,
    "S": 3,
}
_DATE_TIME_LITERAL_CHARACTERS = frozenset("-_. :/T")


def render_date_time_template(
    value: object,
    *,
    current_time: datetime | None = None,
    context: Mapping[str, str] | None = None,
) -> str:
    """展开通用日期时间块和显式上下文占位符。

    字段宽度规则：
    - 年使用 ``Y`` 到 ``YYYY``；
    - 月、日、时、分、秒使用一位或两位字段；
    - 毫秒使用 ``S`` 到 ``SSS``。

    短字段从对应固定宽度值的右侧取值，例如 2026 年的 ``YY`` 是 ``26``，
    21 日的 ``D`` 是 ``1``。所有块在一次调用中使用同一个时间点。
    """

    if not isinstance(value, str):
        raise _invalid_template_error(
            template="",
            expression=None,
            reason="模板必须是字符串",
        )

    template = value
    resolved_time = current_time or datetime.now().astimezone()
    rendered_parts: list[str] = []
    cursor = 0
    for match in _DATE_TIME_BLOCK_PATTERN.finditer(template):
        literal = template[cursor : match.start()]
        if "{" in literal or "}" in literal:
            raise _invalid_template_error(
                template=template,
                expression=None,
                reason="日期时间格式大括号不完整",
            )
        rendered_parts.append(literal)
        expression = match.group(1)
        if not expression:
            rendered_parts.append(
                _render_date_time_expression(
                    expression,
                    current_time=resolved_time,
                    template=template,
                )
            )
        elif context is not None and expression in context:
            context_value = context[expression]
            if not isinstance(context_value, str):
                raise _invalid_template_error(
                    template=template,
                    expression=expression,
                    reason="上下文占位符值必须是字符串",
                )
            rendered_parts.append(context_value)
        else:
            rendered_parts.append(
                _render_date_time_expression(
                    expression,
                    current_time=resolved_time,
                    template=template,
                )
            )
        cursor = match.end()

    remainder = template[cursor:]
    if "{" in remainder or "}" in remainder:
        raise _invalid_template_error(
            template=template,
            expression=None,
            reason="日期时间格式大括号不完整",
        )
    rendered_parts.append(remainder)
    return "".join(rendered_parts)


def _render_date_time_expression(
    expression: str,
    *,
    current_time: datetime,
    template: str,
) -> str:
    """按字段宽度上限展开一个日期时间表达式。"""

    if not expression:
        raise _invalid_template_error(
            template=template,
            expression=expression,
            reason="日期时间格式不能为空",
        )

    field_values = {
        "Y": f"{current_time.year:04d}",
        "M": f"{current_time.month:02d}",
        "D": f"{current_time.day:02d}",
        "h": f"{current_time.hour:02d}",
        "m": f"{current_time.minute:02d}",
        "s": f"{current_time.second:02d}",
        "S": f"{current_time.microsecond // 1000:03d}",
    }
    rendered: list[str] = []
    field_count = 0
    offset = 0
    while offset < len(expression):
        marker = expression[offset]
        max_width = _FIELD_MAX_WIDTHS.get(marker)
        if max_width is not None:
            end = offset + 1
            while end < len(expression) and expression[end] == marker:
                end += 1
            width = end - offset
            if width > max_width:
                raise _invalid_template_error(
                    template=template,
                    expression=expression,
                    reason=(
                        f"字段 {marker * width} 超过最大宽度 {max_width}"
                    ),
                    field=marker,
                    width=width,
                    max_width=max_width,
                )
            rendered.append(field_values[marker][-width:])
            field_count += 1
            offset = end
            continue

        if marker not in _DATE_TIME_LITERAL_CHARACTERS:
            raise _invalid_template_error(
                template=template,
                expression=expression,
                reason=f"不支持的日期时间格式内容：{marker}",
            )
        rendered.append(marker)
        offset += 1

    if field_count == 0:
        raise _invalid_template_error(
            template=template,
            expression=expression,
            reason="日期时间格式至少需要一个字段",
        )
    return "".join(rendered)


def _invalid_template_error(
    *,
    template: str,
    expression: str | None,
    reason: str,
    field: str | None = None,
    width: int | None = None,
    max_width: int | None = None,
) -> InvalidRequestError:
    """构造所有节点共用的稳定日期时间模板错误。"""

    details: dict[str, object] = {
        "template": template,
        "reason": reason,
    }
    if expression is not None:
        details["expression"] = expression
    if field is not None:
        details["field"] = field
    if width is not None:
        details["width"] = width
    if max_width is not None:
        details["max_width"] = max_width
    return InvalidRequestError("日期时间模板不合法", details=details)
