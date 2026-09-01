"""Workflow Image Save 文件名时间模板解析。"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Mapping

from backend.service.application.errors import InvalidRequestError


_TIME_BLOCK_PATTERN = re.compile(r"\{([^{}]*)\}")
_TIME_TOKENS = ("YYYY", "SSS", "MM", "DD", "hh", "mm", "ss")
_TIME_LITERAL_CHARACTERS = frozenset("-_. T")
_INVALID_FILE_NAME_CHARACTERS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_FILE_STEMS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_SUPPORTED_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def render_image_file_name_template(
    value: object,
    *,
    current_time: datetime | None = None,
    context: Mapping[str, str] | None = None,
) -> str:
    """展开 Image Save 文件名中的时间块并返回合法文件名。

    固定文本位于大括号外。大括号内只允许 ``YYYY``、``MM``、``DD``、
    ``hh``、``mm``、``ss``、``SSS`` 和文件名安全的分隔字符。
    """

    template = value.strip() if isinstance(value, str) else ""
    if not template:
        raise InvalidRequestError("Image Save 文件名不能为空")

    resolved_time = current_time or datetime.now().astimezone()
    rendered_parts: list[str] = []
    cursor = 0
    for match in _TIME_BLOCK_PATTERN.finditer(template):
        literal = template[cursor : match.start()]
        if "{" in literal or "}" in literal:
            raise _invalid_template_error(template, "时间格式大括号不完整")
        rendered_parts.append(literal)
        expression = match.group(1)
        context_value = context.get(expression) if context is not None else None
        rendered_parts.append(
            context_value
            if context_value is not None
            else _render_time_expression(
                expression,
                current_time=resolved_time,
                template=template,
            )
        )
        cursor = match.end()

    remainder = template[cursor:]
    if "{" in remainder or "}" in remainder:
        raise _invalid_template_error(template, "时间格式大括号不完整")
    rendered_parts.append(remainder)

    file_name = "".join(rendered_parts)
    _validate_image_file_name(file_name, template=template)
    return file_name


def image_media_type_for_file_name(file_name: str) -> str:
    """返回受支持图片文件名对应的媒体类型。"""

    suffix = PurePosixPath(file_name).suffix.lower()
    media_type = _SUPPORTED_IMAGE_MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise InvalidRequestError(
            "Image Save 文件扩展名不受支持",
            details={
                "file_name": file_name,
                "supported_extensions": sorted(_SUPPORTED_IMAGE_MEDIA_TYPES),
            },
        )
    return media_type


def _render_time_expression(
    expression: str,
    *,
    current_time: datetime,
    template: str,
) -> str:
    """按严格 token 规则展开单个时间表达式。"""

    if not expression:
        raise _invalid_template_error(template, "时间格式不能为空")

    values = {
        "YYYY": f"{current_time.year:04d}",
        "MM": f"{current_time.month:02d}",
        "DD": f"{current_time.day:02d}",
        "hh": f"{current_time.hour:02d}",
        "mm": f"{current_time.minute:02d}",
        "ss": f"{current_time.second:02d}",
        "SSS": f"{current_time.microsecond // 1000:03d}",
    }
    rendered: list[str] = []
    token_count = 0
    offset = 0
    while offset < len(expression):
        matched_token = next(
            (
                token
                for token in _TIME_TOKENS
                if expression.startswith(token, offset)
            ),
            None,
        )
        if matched_token is not None:
            rendered.append(values[matched_token])
            token_count += 1
            offset += len(matched_token)
            continue
        literal_character = expression[offset]
        if literal_character not in _TIME_LITERAL_CHARACTERS:
            raise _invalid_template_error(
                template,
                f"不支持的时间格式内容：{literal_character}",
            )
        rendered.append(literal_character)
        offset += 1

    if token_count == 0:
        raise _invalid_template_error(template, "时间格式至少需要一个时间标记")
    return "".join(rendered)


def _validate_image_file_name(file_name: str, *, template: str) -> None:
    """执行跨平台安全的单级图片文件名校验。"""

    if (
        not file_name
        or len(file_name) > 255
        or file_name in {".", ".."}
        or PurePosixPath(file_name).name != file_name
        or PureWindowsPath(file_name).name != file_name
        or file_name.endswith((" ", "."))
        or any(
            character in _INVALID_FILE_NAME_CHARACTERS or ord(character) < 32
            for character in file_name
        )
    ):
        raise _invalid_template_error(template, "展开后的文件名不合法")

    windows_device_stem = file_name.split(".", maxsplit=1)[0].rstrip(" .").upper()
    if windows_device_stem in _WINDOWS_RESERVED_FILE_STEMS:
        raise _invalid_template_error(template, "展开后的文件名是系统保留名称")
    image_media_type_for_file_name(file_name)


def _invalid_template_error(template: str, reason: str) -> InvalidRequestError:
    """构造包含稳定错误详情的文件名模板异常。"""

    return InvalidRequestError(
        "Image Save 文件名模板不合法",
        details={"file_name": template, "reason": reason},
    )
