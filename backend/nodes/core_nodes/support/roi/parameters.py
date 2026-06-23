"""ROI 节点参数读取函数。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.roi.geometry import normalize_polygon_xy
from backend.service.application.errors import InvalidRequestError


def read_optional_text(raw_value: object, *, field_name: str, node_name: str) -> str | None:
    """读取可选字符串参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def read_optional_bool(raw_value: object, *, field_name: str, node_name: str) -> bool | None:
    """读取可选布尔参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是布尔值")
    return raw_value


def read_optional_number(raw_value: object, *, field_name: str, node_name: str) -> float | None:
    """读取可选数值参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是数值")
    return float(raw_value)


def read_polygon_parameter(
    raw_value: object,
    *,
    field_name: str,
    node_name: str,
) -> list[list[float]] | None:
    """读取可选 polygon 参数。"""

    if raw_value is None:
        return None
    return normalize_polygon_xy(raw_value, field_name=field_name, node_id=node_name)

