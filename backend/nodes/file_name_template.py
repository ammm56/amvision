"""Workflow 保存节点共用的单级文件名模板。"""

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


def render_file_name_template(
    value: object,
    *,
    node_label: str,
    current_time: datetime | None = None,
    context: Mapping[str, str] | None = None,
) -> str:
    """展开通用日期时间模板，并校验跨平台安全的单级文件名。"""

    template = value.strip() if isinstance(value, str) else ""
    if not template:
        raise InvalidRequestError(f"{node_label} 文件名不能为空")
    file_name = render_date_time_template(
        template,
        current_time=current_time,
        context=context,
    )
    validate_file_name(file_name, template=template, node_label=node_label)
    return file_name


def validate_file_name(
    file_name: str,
    *,
    template: str,
    node_label: str,
) -> None:
    """校验文件名不包含目录、系统保留名称或跨平台非法字符。"""

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
        raise _invalid_file_name_template_error(
            template=template,
            node_label=node_label,
            reason="展开后的文件名不合法",
        )

    windows_device_stem = file_name.split(".", maxsplit=1)[0].rstrip(" .").upper()
    if windows_device_stem in _WINDOWS_RESERVED_FILE_STEMS:
        raise _invalid_file_name_template_error(
            template=template,
            node_label=node_label,
            reason="展开后的文件名是系统保留名称",
        )


def require_file_name_suffix(
    file_name: str,
    *,
    node_label: str,
    supported_suffixes: set[str],
) -> str:
    """读取并校验文件扩展名，返回规范化小写扩展名。"""

    suffix = PurePosixPath(file_name).suffix.lower()
    normalized_suffixes = {item.lower() for item in supported_suffixes}
    if suffix not in normalized_suffixes:
        raise InvalidRequestError(
            f"{node_label} 文件扩展名不受支持",
            details={
                "file_name": file_name,
                "supported_extensions": sorted(normalized_suffixes),
            },
        )
    return suffix


def _invalid_file_name_template_error(
    *,
    template: str,
    node_label: str,
    reason: str,
) -> InvalidRequestError:
    """构造所有 Save 节点共用的文件名模板错误。"""

    return InvalidRequestError(
        f"{node_label} 文件名模板不合法",
        details={"file_name": template, "reason": reason},
    )
