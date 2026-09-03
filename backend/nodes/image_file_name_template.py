"""Workflow 图片文件名校验与媒体类型解析。"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from backend.nodes.file_name_template import (
    render_file_name_template,
    require_file_name_suffix,
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

    file_name = render_file_name_template(
        value,
        node_label="Image Save",
        current_time=current_time,
        context=context,
    )
    image_media_type_for_file_name(file_name)
    return file_name


def image_media_type_for_file_name(file_name: str) -> str:
    """返回受支持图片文件名对应的媒体类型。"""

    suffix = require_file_name_suffix(
        file_name,
        node_label="Image Save",
        supported_suffixes=set(_SUPPORTED_IMAGE_MEDIA_TYPES),
    )
    return _SUPPORTED_IMAGE_MEDIA_TYPES[suffix]
