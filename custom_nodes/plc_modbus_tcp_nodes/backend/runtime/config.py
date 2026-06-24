"""PLC Modbus TCP 节点通用配置构造。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.addresses import (
    _read_byte_position,
    _read_data_type,
    _read_logical_address,
    _read_string_length,
    _read_word_order,
    _validate_read_type_for_address,
    _validate_write_type_for_address,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _normalize_json_value,
    _read_non_negative_int_parameter,
    _read_optional_non_empty_str_parameter,
    _read_positive_float_parameter,
    _read_positive_int_parameter,
    _read_request_overrides,
    _read_required_str_parameter,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    ModbusConnectionConfig,
    ModbusReadConfig,
    ModbusWriteConfig,
)


def _build_read_config(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> ModbusReadConfig:
    """构造通用读值配置。"""

    overrides = _read_request_overrides(request, node_name=node_name)
    connection = _build_connection_config(
        request=request,
        node_name=node_name,
        overrides=overrides,
    )
    logical_address = _read_logical_address(
        field_name="register_address",
        request=request,
        overrides=overrides,
        node_name=node_name,
    )
    data_type = _read_data_type(
        request=request,
        overrides=overrides,
        node_name=node_name,
    )
    _validate_read_type_for_address(
        logical_address=logical_address,
        data_type=data_type,
        node_name=node_name,
    )
    word_order = _read_word_order(
        request=request,
        overrides=overrides,
        node_name=node_name,
    )
    byte_position = _read_byte_position(
        request=request,
        overrides=overrides,
        node_name=node_name,
    )
    string_length = _read_string_length(
        request=request,
        overrides=overrides,
        node_name=node_name,
        data_type=data_type,
        required=data_type == "string",
    )
    string_encoding = _read_optional_non_empty_str_parameter(
        field_name="string_encoding",
        node_name=node_name,
        parameter_value=request.parameters.get("string_encoding"),
        override_value=overrides.get("string_encoding"),
        default_value="utf-8",
    )
    return ModbusReadConfig(
        connection=connection,
        logical_address=logical_address,
        data_type=data_type,
        word_order=word_order,
        byte_position=byte_position,
        string_length=string_length,
        string_encoding=string_encoding,
    )


def _build_write_config(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> ModbusWriteConfig:
    """构造通用写值配置。"""

    overrides = _read_request_overrides(request, node_name=node_name)
    connection = _build_connection_config(
        request=request,
        node_name=node_name,
        overrides=overrides,
    )
    logical_address = _read_logical_address(
        field_name="register_address",
        request=request,
        overrides=overrides,
        node_name=node_name,
    )
    data_type = _read_data_type(
        request=request,
        overrides=overrides,
        node_name=node_name,
    )
    _validate_write_type_for_address(
        logical_address=logical_address,
        data_type=data_type,
        node_name=node_name,
    )
    word_order = _read_word_order(
        request=request,
        overrides=overrides,
        node_name=node_name,
    )
    byte_position = _read_byte_position(
        request=request,
        overrides=overrides,
        node_name=node_name,
    )
    string_length = _read_string_length(
        request=request,
        overrides=overrides,
        node_name=node_name,
        data_type=data_type,
        required=False,
    )
    string_encoding = _read_optional_non_empty_str_parameter(
        field_name="string_encoding",
        node_name=node_name,
        parameter_value=request.parameters.get("string_encoding"),
        override_value=overrides.get("string_encoding"),
        default_value="utf-8",
    )
    raw_value = overrides.get("value", request.parameters.get("value"))
    if raw_value is None:
        raise InvalidRequestError(f"{node_name} 的 value 不能为空")
    normalized_value = _normalize_json_value(
        raw_value, field_name="value", node_name=node_name
    )
    return ModbusWriteConfig(
        connection=connection,
        logical_address=logical_address,
        data_type=data_type,
        word_order=word_order,
        byte_position=byte_position,
        string_length=string_length,
        string_encoding=string_encoding,
        value=normalized_value,
    )


def _build_connection_config(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
    overrides: dict[str, object],
) -> ModbusConnectionConfig:
    """构造连接参数。"""

    host = _read_required_str_parameter(
        field_name="host",
        node_name=node_name,
        parameter_value=request.parameters.get("host"),
        override_value=overrides.get("host"),
    )
    port = _read_positive_int_parameter(
        field_name="port",
        node_name=node_name,
        parameter_value=request.parameters.get("port"),
        override_value=overrides.get("port"),
        default_value=502,
    )
    if port > 65535:
        raise InvalidRequestError(f"{node_name} 的 port 必须在 1 到 65535 之间")
    unit_id = _read_positive_int_parameter(
        field_name="unit_id",
        node_name=node_name,
        parameter_value=request.parameters.get("unit_id"),
        override_value=overrides.get("unit_id"),
        default_value=1,
    )
    if unit_id > 255:
        raise InvalidRequestError(f"{node_name} 的 unit_id 必须在 1 到 255 之间")
    timeout_seconds = _read_positive_float_parameter(
        field_name="timeout_seconds",
        node_name=node_name,
        parameter_value=request.parameters.get("timeout_seconds"),
        override_value=overrides.get("timeout_seconds"),
        default_value=3.0,
    )
    retries = _read_non_negative_int_parameter(
        field_name="retries",
        node_name=node_name,
        parameter_value=request.parameters.get("retries"),
        override_value=overrides.get("retries"),
        default_value=1,
    )
    return ModbusConnectionConfig(
        host=host,
        port=port,
        unit_id=unit_id,
        timeout_seconds=timeout_seconds,
        retries=retries,
        request_source="request-input" if overrides else "parameters",
    )
