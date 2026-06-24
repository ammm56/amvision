"""PLC Modbus TCP 结果信号回写配置解析。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.addresses import (
    _parse_data_type_value,
    _parse_logical_address_value,
    _parse_string_length_value,
    _validate_write_type_for_address,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.config import (
    _build_connection_config,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _normalize_json_value,
    _read_boolean_mapping_value,
    _read_boolean_parameter,
    _read_disabled_signals,
    _read_named_byte_position,
    _read_named_word_order,
    _read_optional_mapping_str,
    _read_optional_non_empty_str_parameter,
    _read_request_signal_values,
    _read_required_mapping_str,
    _read_signal_source_scope,
    _read_truth_mapping_values,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    BytePosition,
    ModbusSignalMappingConfig,
    ModbusWriteResultSignalsConfig,
    WordOrder,
)


def build_write_result_signals_config(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
    overrides: dict[str, object],
) -> ModbusWriteResultSignalsConfig:
    """构造结果回写节点的完整运行配置。"""

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
        mapping = build_signal_mapping_config(
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


def build_signal_mapping_config(
    *,
    raw_mapping: dict[str, object],
    mapping_index: int,
    default_word_order: WordOrder,
    default_byte_position: BytePosition,
    default_string_encoding: str,
    node_name: str,
) -> ModbusSignalMappingConfig:
    """构造单个结果信号映射配置。"""

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
