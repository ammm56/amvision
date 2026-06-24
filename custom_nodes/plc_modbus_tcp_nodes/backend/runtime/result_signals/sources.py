"""PLC Modbus TCP 结果信号来源取值。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _coerce_condition_like_value,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    ModbusSignalMappingConfig,
    ResolvedSignalValue,
    SignalSourceScope,
)

_MISSING_SOURCE_VALUE = object()


def resolve_signal_value(
    *,
    mapping: ModbusSignalMappingConfig,
    result_payload: dict[str, object],
    alarm_payload: dict[str, object] | None,
    request_overrides: dict[str, object],
    request_signal_values: dict[str, object],
    disabled_signals: frozenset[str],
    node_name: str,
) -> ResolvedSignalValue:
    """解析单个信号映射的最终写入值。"""

    if not mapping.enabled:
        return ResolvedSignalValue(
            signal_name=mapping.signal_name,
            source_scope=mapping.source_scope,
            source_path=mapping.source_path,
            source_label="mapping-disabled",
            value=None,
            skip_reason="mapping_disabled",
        )
    if mapping.signal_name in disabled_signals:
        return ResolvedSignalValue(
            signal_name=mapping.signal_name,
            source_scope=mapping.source_scope,
            source_path=mapping.source_path,
            source_label="request.disabled_signals",
            value=None,
            skip_reason="disabled_by_request",
        )
    if mapping.signal_name in request_signal_values:
        return ResolvedSignalValue(
            signal_name=mapping.signal_name,
            source_scope="request",
            source_path=f"signal_values.{mapping.signal_name}",
            source_label=f"request.signal_values.{mapping.signal_name}",
            value=request_signal_values[mapping.signal_name],
            skip_reason=None,
        )

    if mapping.source_scope == "literal":
        source_value = mapping.literal_value
        source_label = f"literal.{mapping.signal_name}"
    else:
        source_root = resolve_signal_source_root(
            source_scope=mapping.source_scope,
            result_payload=result_payload,
            alarm_payload=alarm_payload,
            request_overrides=request_overrides,
        )
        if source_root is None:
            if mapping.skip_when_missing:
                return ResolvedSignalValue(
                    signal_name=mapping.signal_name,
                    source_scope=mapping.source_scope,
                    source_path=mapping.source_path,
                    source_label=f"{mapping.source_scope}.{mapping.source_path}",
                    value=None,
                    skip_reason="source_scope_missing",
                )
            raise InvalidRequestError(
                f"{node_name} 的 signal {mapping.signal_name} 缺少来源对象",
                details={"source_scope": mapping.source_scope},
            )
        assert mapping.source_path is not None
        source_value = resolve_object_path_value(
            source_root=source_root,
            source_path=mapping.source_path,
        )
        source_label = f"{mapping.source_scope}.{mapping.source_path}"

    if source_value is _MISSING_SOURCE_VALUE:
        if mapping.skip_when_missing:
            return ResolvedSignalValue(
                signal_name=mapping.signal_name,
                source_scope=mapping.source_scope,
                source_path=mapping.source_path,
                source_label=source_label,
                value=None,
                skip_reason="source_value_missing",
            )
        raise InvalidRequestError(
            f"{node_name} 的 signal {mapping.signal_name} 缺少来源值",
            details={
                "source_scope": mapping.source_scope,
                "source_path": mapping.source_path,
            },
        )

    effective_value = source_value
    if mapping.true_value is not None or mapping.false_value is not None:
        truth_value = _coerce_condition_like_value(
            raw_value=source_value,
            node_name=node_name,
            field_name=f"signal {mapping.signal_name}",
        )
        effective_value = mapping.true_value if truth_value else mapping.false_value
    return ResolvedSignalValue(
        signal_name=mapping.signal_name,
        source_scope=mapping.source_scope,
        source_path=mapping.source_path,
        source_label=source_label,
        value=effective_value,
        skip_reason=None,
    )


def resolve_signal_source_root(
    *,
    source_scope: SignalSourceScope,
    result_payload: dict[str, object],
    alarm_payload: dict[str, object] | None,
    request_overrides: dict[str, object],
) -> dict[str, object] | None:
    """按来源域返回可读取的对象根。"""

    if source_scope == "result":
        return result_payload
    if source_scope == "alarm":
        return alarm_payload
    if source_scope == "request":
        return request_overrides
    return None


def resolve_object_path_value(
    *,
    source_root: dict[str, object],
    source_path: str,
) -> object:
    """按点路径读取对象中的值。"""

    current_value: object = source_root
    for path_segment in source_path.split("."):
        normalized_segment = path_segment.strip()
        if not normalized_segment:
            return _MISSING_SOURCE_VALUE
        if (
            not isinstance(current_value, dict)
            or normalized_segment not in current_value
        ):
            return _MISSING_SOURCE_VALUE
        current_value = current_value[normalized_segment]
    return current_value
