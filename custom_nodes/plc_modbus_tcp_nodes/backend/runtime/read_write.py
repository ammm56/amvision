"""PLC Modbus TCP 通用读写执行。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.client import (
    ProjectModbusTcpClient,
    _build_response_meta,
    _open_modbus_client,
    _raise_as_service_error,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.codec import (
    _decode_observed_value,
    _encode_register_values,
    _resolve_register_count,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.config import (
    _build_read_config,
    _build_write_config,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _coerce_bool_value,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    ModbusReadConfig,
    ModbusWriteConfig,
)


def execute_read_value_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行一次通用读值节点。"""

    config = _build_read_config(request=request, node_name=node_name)
    with _open_modbus_client(config.connection, node_name=node_name) as client:
        result_value = _perform_read_operation(
            client=client, config=config, node_name=node_name
        )
    return {"result": build_value_payload(result_value)}


def execute_write_value_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行一次通用写值节点。"""

    config = _build_write_config(request=request, node_name=node_name)
    with _open_modbus_client(config.connection, node_name=node_name) as client:
        result_value = _perform_write_operation(
            client=client, config=config, node_name=node_name
        )
    return {"result": build_value_payload(result_value)}


def _perform_read_operation(
    *,
    client: ProjectModbusTcpClient,
    config: ModbusReadConfig,
    node_name: str,
) -> dict[str, object]:
    """执行一次读取并规整输出。"""

    try:
        if config.logical_address.family == "coil":
            response = client.read_coils(
                config.logical_address.zero_based_address,
                count=1,
                device_id=config.connection.unit_id,
            )
            raw_values: list[bool | int] = [bool(item) for item in response.bits]
        elif config.logical_address.family == "discrete_input":
            response = client.read_discrete_inputs(
                config.logical_address.zero_based_address,
                count=1,
                device_id=config.connection.unit_id,
            )
            raw_values = [bool(item) for item in response.bits]
        elif config.logical_address.family == "input_register":
            register_count = _resolve_register_count(config=config, node_name=node_name)
            response = client.read_input_registers(
                config.logical_address.zero_based_address,
                count=register_count,
                device_id=config.connection.unit_id,
            )
            raw_values = [int(item) for item in response.registers]
        else:
            register_count = _resolve_register_count(config=config, node_name=node_name)
            response = client.read_holding_registers(
                config.logical_address.zero_based_address,
                count=register_count,
                device_id=config.connection.unit_id,
            )
            raw_values = [int(item) for item in response.registers]
    except Exception as exc:  # pragma: no cover - 由统一错误翻译兜底
        _raise_as_service_error(
            exc=exc, node_name=node_name, connection=config.connection
        )

    observed_value = _decode_observed_value(
        config=config,
        raw_values=raw_values,
        node_name=node_name,
    )
    return {
        "transport": "modbus-tcp",
        "operation": "read_value",
        "host": config.connection.host,
        "port": config.connection.port,
        "unit_id": config.connection.unit_id,
        "register_address": config.logical_address.raw_address,
        "register_area": config.logical_address.family,
        "zero_based_address": config.logical_address.zero_based_address,
        "data_type": config.data_type,
        "word_order": config.word_order,
        "byte_position": config.byte_position,
        "string_length": config.string_length,
        "string_encoding": config.string_encoding,
        "raw_values": list(raw_values),
        "observed_value": observed_value,
        "request_source": config.connection.request_source,
        "response_meta": _build_response_meta(response),
    }


def _perform_write_operation(
    *,
    client: ProjectModbusTcpClient,
    config: ModbusWriteConfig,
    node_name: str,
) -> dict[str, object]:
    """执行一次写入并规整输出。"""

    try:
        if config.logical_address.family == "coil":
            normalized_bool = _coerce_bool_value(
                raw_value=config.value,
                node_name=node_name,
                field_name="value",
            )
            response = client.write_single_coil(
                config.logical_address.zero_based_address,
                normalized_bool,
                device_id=config.connection.unit_id,
            )
            encoded_registers: list[int] = []
            normalized_value: object = normalized_bool
        else:
            encoded_registers = _encode_register_values(
                config=config, node_name=node_name
            )
            normalized_value = config.value
            if len(encoded_registers) == 1:
                response = client.write_single_register(
                    config.logical_address.zero_based_address,
                    encoded_registers[0],
                    device_id=config.connection.unit_id,
                )
            else:
                response = client.write_multiple_registers(
                    config.logical_address.zero_based_address,
                    encoded_registers,
                    device_id=config.connection.unit_id,
                )
    except Exception as exc:  # pragma: no cover - 由统一错误翻译兜底
        _raise_as_service_error(
            exc=exc, node_name=node_name, connection=config.connection
        )

    return {
        "transport": "modbus-tcp",
        "operation": "write_value",
        "host": config.connection.host,
        "port": config.connection.port,
        "unit_id": config.connection.unit_id,
        "register_address": config.logical_address.raw_address,
        "register_area": config.logical_address.family,
        "zero_based_address": config.logical_address.zero_based_address,
        "data_type": config.data_type,
        "word_order": config.word_order,
        "byte_position": config.byte_position,
        "string_length": config.string_length,
        "string_encoding": config.string_encoding,
        "requested_value": normalized_value,
        "encoded_registers": encoded_registers,
        "acknowledged_count": response.count,
        "request_source": config.connection.request_source,
        "response_meta": _build_response_meta(response),
    }
