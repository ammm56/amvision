"""PLC Modbus TCP 节点参数读取与 JSON 值规整。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    BytePosition,
    SignalSourceScope,
    WaitOperator,
    WordOrder,
)


def _read_request_overrides(
    request: WorkflowNodeExecutionRequest,
    *,
    node_name: str,
) -> dict[str, object]:
    """读取可选 request 输入覆盖对象。"""

    raw_payload = request.input_values.get("request")
    if raw_payload is None:
        return {}
    value_payload = require_value_payload(raw_payload, field_name="request")
    value = value_payload["value"]
    if not isinstance(value, dict):
        raise InvalidRequestError(f"{node_name} 的 request 输入必须是对象")
    return dict(value)


def _read_request_signal_values(
    *,
    overrides: dict[str, object],
    node_name: str,
) -> dict[str, object]:
    """读取 request 中的 signal_values 覆盖。"""

    raw_value = overrides.get("signal_values")
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"{node_name} 的 request.signal_values 必须是对象")
    return {
        str(key): _normalize_json_value(
            item,
            field_name=f"signal_values.{key}",
            node_name=node_name,
        )
        for key, item in raw_value.items()
    }


def _read_disabled_signals(
    *,
    overrides: dict[str, object],
    node_name: str,
) -> frozenset[str]:
    """读取 request 中的 disabled_signals。"""

    raw_value = overrides.get("disabled_signals")
    if raw_value is None:
        return frozenset()
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 的 request.disabled_signals 必须是数组")
    normalized_values: list[str] = []
    for item_index, item in enumerate(raw_value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise InvalidRequestError(
                f"{node_name} 的 request.disabled_signals[{item_index}] 必须是非空字符串"
            )
        normalized_values.append(item.strip())
    return frozenset(normalized_values)


def _read_signal_source_scope(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> SignalSourceScope:
    """读取 signal source scope。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"result", "alarm", "request", "literal"}:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 不支持当前取值",
            details={"source_scope": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_required_mapping_str(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> str:
    """读取映射中的必填字符串。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_optional_mapping_str(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: str | None = None,
) -> str | None:
    """读取映射中的可选字符串。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_boolean_mapping_value(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: bool,
) -> bool:
    """读取映射中的布尔配置。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是布尔值")
    return raw_value


def _read_truth_mapping_values(
    *,
    raw_mapping: dict[str, object],
    field_prefix: str,
    node_name: str,
) -> tuple[object | None, object | None]:
    """读取 true_value / false_value。"""

    has_true_value = "true_value" in raw_mapping
    has_false_value = "false_value" in raw_mapping
    if has_true_value != has_false_value:
        raise InvalidRequestError(
            f"{node_name} 的 {field_prefix}.true_value 与 false_value 必须同时提供"
        )
    if not has_true_value:
        return None, None
    true_value = _normalize_json_value(
        raw_mapping.get("true_value"),
        field_name=f"{field_prefix}.true_value",
        node_name=node_name,
    )
    false_value = _normalize_json_value(
        raw_mapping.get("false_value"),
        field_name=f"{field_prefix}.false_value",
        node_name=node_name,
    )
    return true_value, false_value


def _coerce_condition_like_value(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> bool:
    """把常见判定值规整成布尔语义。"""

    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return raw_value != 0
    if isinstance(raw_value, str):
        normalized_value = raw_value.strip().lower()
        if normalized_value in {"ok", "true", "1", "yes", "on"}:
            return True
        if normalized_value in {"ng", "false", "0", "no", "off"}:
            return False
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 无法按 true_value/false_value 规则转换为布尔语义",
        details={"actual_value": raw_value},
    )


def _read_wait_operator(
    *,
    node_name: str,
    parameter_value: object,
    override_value: object,
) -> WaitOperator:
    """读取等待条件运算符。"""

    raw_value = override_value if override_value is not None else parameter_value
    if raw_value is None:
        return "eq"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 operator 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "eq",
        "ne",
        "gt",
        "ge",
        "lt",
        "le",
        "contains",
        "bitmask_any_set",
        "bitmask_all_set",
    }:
        raise InvalidRequestError(
            f"{node_name} 的 operator 不支持当前取值",
            details={"operator": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_named_word_order(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: WordOrder,
) -> WordOrder:
    """读取任意命名的 word_order 字段。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"big", "little"}:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 仅支持 big 或 little")
    return normalized_value  # type: ignore[return-value]


def _read_named_byte_position(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: BytePosition,
) -> BytePosition:
    """读取任意命名的 byte_position 字段。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"low", "high"}:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 仅支持 low 或 high")
    return normalized_value  # type: ignore[return-value]


def _coerce_bool_value(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> bool:
    """读取布尔值。"""

    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是布尔值")
    return raw_value


def _coerce_int_value(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """读取整数值并校验范围。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是整数")
    if raw_value < minimum or raw_value > maximum:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 超出允许范围",
            details={"minimum": minimum, "maximum": maximum, "actual": raw_value},
        )
    return raw_value


def _coerce_float_value(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> float:
    """读取浮点值。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是数字")
    return float(raw_value)


def _read_boolean_parameter(
    *,
    field_name: str,
    node_name: str,
    parameter_value: object,
    override_value: object,
    default_value: bool,
) -> bool:
    """读取布尔参数。"""

    raw_value = override_value if override_value is not None else parameter_value
    if raw_value is None:
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是布尔值")
    return raw_value


def _read_required_str_parameter(
    *,
    field_name: str,
    node_name: str,
    parameter_value: object,
    override_value: object,
) -> str:
    """读取必填字符串字段。"""

    raw_value = override_value if override_value is not None else parameter_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_optional_non_empty_str_parameter(
    *,
    field_name: str,
    node_name: str,
    parameter_value: object,
    override_value: object,
    default_value: str,
) -> str:
    """读取可选字符串字段。"""

    raw_value = override_value if override_value is not None else parameter_value
    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_positive_int_parameter(
    *,
    field_name: str,
    node_name: str,
    parameter_value: object,
    override_value: object,
    default_value: int,
) -> int:
    """读取正整数参数。"""

    raw_value = override_value if override_value is not None else parameter_value
    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须大于 0")
    return raw_value


def _read_non_negative_int_parameter(
    *,
    field_name: str,
    node_name: str,
    parameter_value: object,
    override_value: object,
    default_value: int,
) -> int:
    """读取非负整数参数。"""

    raw_value = override_value if override_value is not None else parameter_value
    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 不能小于 0")
    return raw_value


def _read_positive_float_parameter(
    *,
    field_name: str,
    node_name: str,
    parameter_value: object,
    override_value: object,
    default_value: float,
) -> float:
    """读取正数参数。"""

    raw_value = override_value if override_value is not None else parameter_value
    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是数字")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须大于 0")
    return normalized_value


def _read_optional_positive_float_parameter(
    *,
    field_name: str,
    node_name: str,
    parameter_present: bool,
    parameter_value: object,
    override_present: bool,
    override_value: object,
    default_value: float | None,
) -> float | None:
    """读取允许显式 null 的正数参数。"""

    if override_present:
        raw_value = override_value
    elif parameter_present:
        raw_value = parameter_value
    else:
        return default_value
    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是数字或 null")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须大于 0")
    return normalized_value


def _normalize_json_value(
    raw_value: object,
    *,
    field_name: str,
    node_name: str,
) -> object:
    """把覆盖输入里的值约束为 JSON 安全对象。"""

    if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
        return raw_value
    if isinstance(raw_value, list):
        return [
            _normalize_json_value(item, field_name=field_name, node_name=node_name)
            for item in raw_value
        ]
    if isinstance(raw_value, dict):
        return {
            str(key): _normalize_json_value(
                item, field_name=field_name, node_name=node_name
            )
            for key, item in raw_value.items()
        }
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 只支持 JSON 安全值",
        details={"value_type": raw_value.__class__.__name__},
    )
