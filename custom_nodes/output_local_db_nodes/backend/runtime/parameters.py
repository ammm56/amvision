"""本地数据库输出节点参数读取。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.output_local_db_nodes.backend.runtime.types import OnMissingPolicy


def _read_on_missing_policy(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: OnMissingPolicy,
) -> OnMissingPolicy:
    """读取缺失策略，未提供时使用默认值。"""

    if raw_value is None:
        return default_value
    return (
        _read_optional_on_missing_policy(
            raw_value=raw_value,
            node_name=node_name,
            field_name=field_name,
        )
        or default_value
    )


def _read_optional_on_missing_policy(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> OnMissingPolicy | None:
    """读取可选缺失策略。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"error", "skip", "null"}:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 不支持当前取值",
            details={"on_missing": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_optional_object_parameter(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> dict[str, object]:
    """读取可选对象参数。"""

    if raw_value is None:
        return {}
    normalized_value = build_value_payload(raw_value)["value"]
    if not isinstance(normalized_value, dict):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是对象")
    return normalized_value


def _read_required_non_empty_string(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> str:
    """读取必填非空字符串。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_optional_non_empty_string(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> str | None:
    """读取可选非空字符串。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_required_string_list(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    require_non_empty: bool,
) -> tuple[str, ...]:
    """读取必填字符串列表。"""

    values = _read_optional_string_list(
        raw_value=raw_value,
        node_name=node_name,
        field_name=field_name,
    )
    if values is None or (require_non_empty and not values):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 至少需要 1 项")
    return values


def _read_optional_string_list(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> tuple[str, ...] | None:
    """读取可选字符串列表。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是数组")
    normalized_values: list[str] = []
    for index, item in enumerate(raw_value):
        if not isinstance(item, str) or not item.strip():
            raise InvalidRequestError(
                f"{node_name} 的 {field_name}[{index}] 必须是非空字符串"
            )
        normalized_item = item.strip()
        if normalized_item not in normalized_values:
            normalized_values.append(normalized_item)
    return tuple(normalized_values)


def _read_boolean_parameter(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: bool,
) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是布尔值")
    return raw_value


def _read_optional_positive_float(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> float | None:
    """读取可选正浮点参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是数字")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须大于 0")
    return normalized_value
