"""PLC Modbus TCP 结果信号回写。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.inspection_record import (
    require_alarm_record_payload,
    require_ok_ng_value,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.addresses import (
    _parse_data_type_value,
    _parse_logical_address_value,
    _parse_string_length_value,
    _validate_write_type_for_address,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.client import _open_modbus_client
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.config import (
    _build_connection_config,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _coerce_condition_like_value,
    _normalize_json_value,
    _read_boolean_mapping_value,
    _read_boolean_parameter,
    _read_disabled_signals,
    _read_named_byte_position,
    _read_named_word_order,
    _read_optional_mapping_str,
    _read_optional_non_empty_str_parameter,
    _read_request_overrides,
    _read_request_signal_values,
    _read_required_mapping_str,
    _read_signal_source_scope,
    _read_truth_mapping_values,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.read_write import (
    _perform_write_operation,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    BytePosition,
    ModbusSignalMappingConfig,
    ModbusWriteConfig,
    ModbusWriteResultSignalsConfig,
    ResolvedSignalValue,
    SignalSourceScope,
    WordOrder,
)

_MISSING_SOURCE_VALUE = object()


def execute_write_result_signals_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行结果对象到 Modbus 点位的回写。"""

    request_overrides = _read_request_overrides(request, node_name=node_name)
    config = _build_write_result_signals_config(
        request=request,
        node_name=node_name,
        overrides=request_overrides,
    )
    result_payload = _require_result_record_payload(
        request.input_values.get("result"),
        field_name="result",
        node_name=node_name,
    )
    alarm_payload = _read_effective_alarm_payload(
        explicit_alarm_payload=request.input_values.get("alarm"),
        result_payload=result_payload,
        node_name=node_name,
    )
    written_items: list[dict[str, object]] = []
    skipped_items: list[dict[str, object]] = []
    failed_items: list[dict[str, object]] = []

    with _open_modbus_client(config.connection, node_name=node_name) as client:
        for mapping in config.mappings:
            resolved_value = _resolve_signal_value(
                mapping=mapping,
                result_payload=result_payload,
                alarm_payload=alarm_payload,
                request_overrides=request_overrides,
                request_signal_values=config.request_signal_values,
                disabled_signals=config.disabled_signals,
                node_name=node_name,
            )
            if resolved_value.skip_reason is not None:
                skipped_items.append(
                    {
                        "signal_name": mapping.signal_name,
                        "source_scope": resolved_value.source_scope,
                        "source_path": resolved_value.source_path,
                        "reason": resolved_value.skip_reason,
                    }
                )
                continue
            write_config = ModbusWriteConfig(
                connection=config.connection,
                logical_address=mapping.logical_address,
                data_type=mapping.data_type,
                word_order=mapping.word_order,
                byte_position=mapping.byte_position,
                string_length=mapping.string_length,
                string_encoding=mapping.string_encoding,
                value=resolved_value.value,
            )
            try:
                write_result = _perform_write_operation(
                    client=client,
                    config=write_config,
                    node_name=f"{node_name}.{mapping.signal_name}",
                )
            except ServiceError as exc:
                failed_item = {
                    "signal_name": mapping.signal_name,
                    "source_scope": resolved_value.source_scope,
                    "source_path": resolved_value.source_path,
                    "register_address": mapping.logical_address.raw_address,
                    "data_type": mapping.data_type,
                    "value": resolved_value.value,
                    "error": exc.message,
                    "error_code": exc.code,
                }
                failed_items.append(failed_item)
                if not config.continue_on_error:
                    raise
                continue
            written_items.append(
                {
                    "signal_name": mapping.signal_name,
                    "source_scope": resolved_value.source_scope,
                    "source_path": resolved_value.source_path,
                    "source_label": resolved_value.source_label,
                    "register_address": mapping.logical_address.raw_address,
                    "register_area": mapping.logical_address.family,
                    "zero_based_address": mapping.logical_address.zero_based_address,
                    "data_type": mapping.data_type,
                    "value": resolved_value.value,
                    "encoded_registers": write_result["encoded_registers"],
                    "acknowledged_count": write_result["acknowledged_count"],
                    "response_meta": write_result["response_meta"],
                }
            )

    return {
        "result": build_value_payload(
            {
                "transport": "modbus-tcp",
                "operation": "write_result_signals",
                "host": config.connection.host,
                "port": config.connection.port,
                "unit_id": config.connection.unit_id,
                "mapping_count": len(config.mappings),
                "written_count": len(written_items),
                "skipped_count": len(skipped_items),
                "failed_count": len(failed_items),
                "written_items": written_items,
                "skipped_items": skipped_items,
                "failed_items": failed_items,
                "request_source": config.connection.request_source,
            }
        )
    }


def _build_write_result_signals_config(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
    overrides: dict[str, object],
) -> ModbusWriteResultSignalsConfig:
    """构造结果回写节点配置。"""

    connection = _build_connection_config(
        request=request,
        node_name=node_name,
        overrides=overrides,
    )
    continue_on_error = _read_boolean_parameter(
        field_name="continue_on_error",
        node_name=node_name,
        parameter_value=request.parameters.get("continue_on_error"),
        override_value=overrides.get("continue_on_error"),
        default_value=False,
    )
    default_word_order = _read_named_word_order(
        raw_value=overrides.get(
            "default_word_order", request.parameters.get("default_word_order")
        ),
        node_name=node_name,
        field_name="default_word_order",
        default_value="big",
    )
    default_byte_position = _read_named_byte_position(
        raw_value=overrides.get(
            "default_byte_position", request.parameters.get("default_byte_position")
        ),
        node_name=node_name,
        field_name="default_byte_position",
        default_value="low",
    )
    default_string_encoding = _read_optional_non_empty_str_parameter(
        field_name="default_string_encoding",
        node_name=node_name,
        parameter_value=request.parameters.get("default_string_encoding"),
        override_value=overrides.get("default_string_encoding"),
        default_value="utf-8",
    )
    raw_mappings = request.parameters.get("signal_mappings")
    if not isinstance(raw_mappings, list) or len(raw_mappings) == 0:
        raise InvalidRequestError(f"{node_name} 的 signal_mappings 必须是非空数组")
    mappings: list[ModbusSignalMappingConfig] = []
    seen_signal_names: set[str] = set()
    for mapping_index, raw_mapping in enumerate(raw_mappings, start=1):
        if not isinstance(raw_mapping, dict):
            raise InvalidRequestError(
                f"{node_name} 的 signal_mappings[{mapping_index}] 必须是对象"
            )
        mapping = _build_signal_mapping_config(
            raw_mapping=raw_mapping,
            mapping_index=mapping_index,
            default_word_order=default_word_order,
            default_byte_position=default_byte_position,
            default_string_encoding=default_string_encoding,
            node_name=node_name,
        )
        if mapping.signal_name in seen_signal_names:
            raise InvalidRequestError(
                f"{node_name} 的 signal_mappings 中 signal_name 不能重复",
                details={"signal_name": mapping.signal_name},
            )
        seen_signal_names.add(mapping.signal_name)
        mappings.append(mapping)
    request_signal_values = _read_request_signal_values(
        overrides=overrides,
        node_name=node_name,
    )
    disabled_signals = _read_disabled_signals(
        overrides=overrides,
        node_name=node_name,
    )
    return ModbusWriteResultSignalsConfig(
        connection=connection,
        continue_on_error=continue_on_error,
        mappings=tuple(mappings),
        request_signal_values=request_signal_values,
        disabled_signals=disabled_signals,
    )


def _build_signal_mapping_config(
    *,
    raw_mapping: dict[str, object],
    mapping_index: int,
    default_word_order: WordOrder,
    default_byte_position: BytePosition,
    default_string_encoding: str,
    node_name: str,
) -> ModbusSignalMappingConfig:
    """构造单个结果回写映射。"""

    field_prefix = f"signal_mappings[{mapping_index}]"
    signal_name = _read_required_mapping_str(
        raw_value=raw_mapping.get("signal_name"),
        node_name=node_name,
        field_name=f"{field_prefix}.signal_name",
    )
    enabled = _read_boolean_mapping_value(
        raw_value=raw_mapping.get("enabled"),
        node_name=node_name,
        field_name=f"{field_prefix}.enabled",
        default_value=True,
    )
    source_scope = _read_signal_source_scope(
        raw_value=raw_mapping.get("source_scope"),
        node_name=node_name,
        field_name=f"{field_prefix}.source_scope",
    )
    source_path = _read_optional_mapping_str(
        raw_value=raw_mapping.get("source_path"),
        node_name=node_name,
        field_name=f"{field_prefix}.source_path",
    )
    if source_scope != "literal" and source_path is None:
        raise InvalidRequestError(f"{node_name} 的 {field_prefix}.source_path 不能为空")
    logical_address = _parse_logical_address_value(
        raw_value=raw_mapping.get("register_address"),
        field_name=f"{field_prefix}.register_address",
        node_name=node_name,
    )
    data_type = _parse_data_type_value(
        raw_value=raw_mapping.get("data_type"),
        field_name=f"{field_prefix}.data_type",
        node_name=node_name,
    )
    _validate_write_type_for_address(
        logical_address=logical_address,
        data_type=data_type,
        node_name=node_name,
    )
    literal_value = None
    if "literal_value" in raw_mapping:
        literal_value = _normalize_json_value(
            raw_mapping.get("literal_value"),
            field_name=f"{field_prefix}.literal_value",
            node_name=node_name,
        )
    if source_scope == "literal" and "literal_value" not in raw_mapping:
        raise InvalidRequestError(
            f"{node_name} 的 {field_prefix}.literal_value 不能为空"
        )
    true_value, false_value = _read_truth_mapping_values(
        raw_mapping=raw_mapping,
        field_prefix=field_prefix,
        node_name=node_name,
    )
    word_order = _read_named_word_order(
        raw_value=raw_mapping.get("word_order"),
        node_name=node_name,
        field_name=f"{field_prefix}.word_order",
        default_value=default_word_order,
    )
    byte_position = _read_named_byte_position(
        raw_value=raw_mapping.get("byte_position"),
        node_name=node_name,
        field_name=f"{field_prefix}.byte_position",
        default_value=default_byte_position,
    )
    string_length = _parse_string_length_value(
        raw_value=raw_mapping.get("string_length"),
        field_name=f"{field_prefix}.string_length",
        node_name=node_name,
        data_type=data_type,
        required=data_type == "string",
    )
    string_encoding = _read_optional_mapping_str(
        raw_value=raw_mapping.get("string_encoding"),
        node_name=node_name,
        field_name=f"{field_prefix}.string_encoding",
        default_value=default_string_encoding,
    )
    skip_when_missing = _read_boolean_mapping_value(
        raw_value=raw_mapping.get("skip_when_missing"),
        node_name=node_name,
        field_name=f"{field_prefix}.skip_when_missing",
        default_value=True,
    )
    return ModbusSignalMappingConfig(
        signal_name=signal_name,
        enabled=enabled,
        source_scope=source_scope,
        source_path=source_path,
        logical_address=logical_address,
        data_type=data_type,
        literal_value=literal_value,
        true_value=true_value,
        false_value=false_value,
        word_order=word_order,
        byte_position=byte_position,
        string_length=string_length,
        string_encoding=string_encoding,
        skip_when_missing=skip_when_missing,
    )


def _resolve_signal_value(
    *,
    mapping: ModbusSignalMappingConfig,
    result_payload: dict[str, object],
    alarm_payload: dict[str, object] | None,
    request_overrides: dict[str, object],
    request_signal_values: dict[str, object],
    disabled_signals: frozenset[str],
    node_name: str,
) -> ResolvedSignalValue:
    """解析单个结果回写映射的最终写入值。"""

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
        source_root = _resolve_signal_source_root(
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
        source_value = _resolve_object_path_value(
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


def _require_result_record_payload(
    raw_payload: object,
    *,
    field_name: str,
    node_name: str,
) -> dict[str, object]:
    """校验结果对象输入。"""

    if not isinstance(raw_payload, dict):
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 输入必须是 result-record 对象"
        )
    ok_ng = require_ok_ng_value(
        raw_payload.get("ok_ng"), field_name=f"{field_name}.ok_ng"
    )
    ok_value = raw_payload.get("ok")
    if not isinstance(ok_value, bool):
        raise InvalidRequestError(f"{node_name} 的 {field_name}.ok 必须是布尔值")
    if ok_value != (ok_ng == "OK"):
        raise InvalidRequestError(
            f"{node_name} 的 {field_name}.ok 与 {field_name}.ok_ng 不一致"
        )
    normalized_payload = dict(raw_payload)
    normalized_payload["ok_ng"] = ok_ng
    normalized_payload["ok"] = ok_value
    alarm_value = raw_payload.get("alarm")
    if alarm_value is not None:
        normalized_payload["alarm"] = require_alarm_record_payload(
            alarm_value,
            field_name=f"{field_name}.alarm",
        )
    return normalized_payload


def _read_effective_alarm_payload(
    *,
    explicit_alarm_payload: object,
    result_payload: dict[str, object],
    node_name: str,
) -> dict[str, object] | None:
    """读取结果回写使用的报警对象。"""

    if explicit_alarm_payload is not None:
        return require_alarm_record_payload(explicit_alarm_payload, field_name="alarm")
    result_alarm_payload = result_payload.get("alarm")
    if result_alarm_payload is None:
        return None
    return require_alarm_record_payload(result_alarm_payload, field_name="result.alarm")


def _resolve_signal_source_root(
    *,
    source_scope: SignalSourceScope,
    result_payload: dict[str, object],
    alarm_payload: dict[str, object] | None,
    request_overrides: dict[str, object],
) -> dict[str, object] | None:
    """按来源域返回可导航的对象根。"""

    if source_scope == "result":
        return result_payload
    if source_scope == "alarm":
        return alarm_payload
    if source_scope == "request":
        return request_overrides
    return None


def _resolve_object_path_value(
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
