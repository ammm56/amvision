"""Core 数值节点共享校验。"""

from __future__ import annotations

import math

from backend.service.application.errors import InvalidRequestError


def require_finite_number(raw_value: object, *, field_name: str) -> int | float:
    """读取有限数值并拒绝 bool、NaN 和 Inf。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    if isinstance(raw_value, float) and not math.isfinite(raw_value):
        raise InvalidRequestError(f"{field_name} 必须是有限数值")
    return raw_value


__all__ = ["require_finite_number"]
