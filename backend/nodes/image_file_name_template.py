"""Workflow 图片文件名校验与媒体类型解析。"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Mapping

from backend.nodes.date_time_template import render_date_time_template
from backend.service.application.errors import InvalidRequestError


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
    """使用通用日期时间模板展开值，再执行图片文件名约束。"""

    template = value.strip() if isinstance(value, str) else ""
    if not template:
        raise InvalidRequestError("Image Save 文件名不能为空")

    file_name = render_date_time_template(
        template,
        current_time=current_time,
        context=context,
    )
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
