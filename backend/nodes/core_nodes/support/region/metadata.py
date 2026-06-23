"""regions.v1 指标输出元数据规范化。"""

from __future__ import annotations


def normalize_optional_int(raw_value: object) -> int | None:
    """规范化可选整数值。"""

    if isinstance(raw_value, bool) or raw_value is None:
        return None
    if not isinstance(raw_value, int):
        return None
    return int(raw_value)


def normalize_optional_text(raw_value: object) -> str | None:
    """规范化可选文本值。"""

    if not isinstance(raw_value, str):
        return None
    normalized_value = raw_value.strip()
    return normalized_value or None

