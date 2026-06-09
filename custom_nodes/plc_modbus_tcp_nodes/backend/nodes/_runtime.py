"""PLC Modbus TCP 节点共享运行时适配层。"""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass
from typing import Literal

from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    compare_values,
    require_value_payload,
)
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceError,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.plc_modbus_tcp_nodes.backend.nodes._modbus_tcp import (
    ModbusBitsReadResponse,
    ModbusRegistersReadResponse,
    ModbusTcpConnectionError,
    ModbusTcpDeviceError,
    ModbusTcpError,
    ModbusTcpProtocolError,
    ModbusTcpTimeoutError,
    ModbusWriteResponse,
    ProjectModbusTcpClient,
)


AddressFamily = Literal["coil", "discrete_input", "input_register", "holding_register"]
ValueDataType = Literal[
    "bool",
    "uint8",
    "int8",
    "uint16",
    "int16",
    "uint32",
    "int32",
    "uint64",
    "int64",
    "float",
    "double",
    "string",
]
WaitOperator = Literal[
    "eq",
    "ne",
    "gt",
    "ge",
    "lt",
    "le",
    "contains",
    "bitmask_any_set",
    "bitmask_all_set",
]
WordOrder = Literal["big", "little"]
BytePosition = Literal["low", "high"]

_REGISTER_VALUE_TYPES: tuple[ValueDataType, ...] = (
    "uint8",
    "int8",
    "uint16",
    "int16",
    "uint32",
    "int32",
    "uint64",
    "int64",
    "float",
    "double",
    "string",
)

_FIXED_REGISTER_COUNTS: dict[ValueDataType, int] = {
    "uint8": 1,
    "int8": 1,
    "uint16": 1,
    "int16": 1,
    "uint32": 2,
    "int32": 2,
    "uint64": 4,
    "int64": 4,
    "float": 2,
    "double": 4,
}


@dataclass(frozen=True)
class ModbusConnectionConfig:
    """描述单次 Modbus TCP 请求使用的连接参数。"""

    host: str
    port: int
    unit_id: int
    timeout_seconds: float
    retries: int
    request_source: str


@dataclass(frozen=True)
class ModbusLogicalAddress:
    """描述一条逻辑寄存器地址。"""

    raw_address: str
    family: AddressFamily
    zero_based_address: int


@dataclass(frozen=True)
class ModbusReadConfig:
    """描述通用读取节点最终配置。"""

    connection: ModbusConnectionConfig
    logical_address: ModbusLogicalAddress
    data_type: ValueDataType
    word_order: WordOrder
    byte_position: BytePosition
    string_length: int | None
    string_encoding: str


@dataclass(frozen=True)
class ModbusWriteConfig:
    """描述通用写入节点最终配置。"""

    connection: ModbusConnectionConfig
    logical_address: ModbusLogicalAddress
    data_type: ValueDataType
    word_order: WordOrder
    byte_position: BytePosition
    string_length: int | None
    string_encoding: str
    value: object


@dataclass(frozen=True)
class ModbusWaitConditionConfig:
    """描述 wait-condition 节点最终配置。"""

    read: ModbusReadConfig
    operator: WaitOperator
    expected_value: object | None
    poll_interval_ms: int
    timeout_seconds: float | None
    stable_match_count: int


def execute_read_value_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行一次通用读值节点。"""

    config = _build_read_config(request=request, node_name=node_name)
    with _open_modbus_client(config.connection, node_name=node_name) as client:
        result_value = _perform_read_operation(client=client, config=config, node_name=node_name)
    return {"result": build_value_payload(result_value)}


def execute_write_value_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行一次通用写值节点。"""

    config = _build_write_config(request=request, node_name=node_name)
    with _open_modbus_client(config.connection, node_name=node_name) as client:
        result_value = _perform_write_operation(client=client, config=config, node_name=node_name)
    return {"result": build_value_payload(result_value)}


def execute_wait_condition_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行 wait-condition 节点。"""

    config = _build_wait_condition_config(request=request, node_name=node_name)
    started_at = time.perf_counter()
    attempts = 0
    consecutive_match_count = 0
    last_result_value: dict[str, object] | None = None

    with _open_modbus_client(config.read.connection, node_name=node_name) as client:
        while True:
            attempts += 1
            last_result_value = _perform_read_operation(
                client=client,
                config=config.read,
                node_name=node_name,
            )
            observed_value = last_result_value["observed_value"]
            matched = _evaluate_wait_condition(
                operator=config.operator,
                observed_value=observed_value,
                expected_value=config.expected_value,
                node_name=node_name,
            )
            if matched:
                consecutive_match_count += 1
                if consecutive_match_count >= config.stable_match_count:
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    return {
                        "result": build_value_payload(
                            {
                                "transport": "modbus-tcp",
                                "operation": "wait_condition",
                                "host": config.read.connection.host,
                                "port": config.read.connection.port,
                                "unit_id": config.read.connection.unit_id,
                                "register_address": config.read.logical_address.raw_address,
                                "address_family": config.read.logical_address.family,
                                "zero_based_address": config.read.logical_address.zero_based_address,
                                "data_type": config.read.data_type,
                                "operator": config.operator,
                                "expected_value": config.expected_value,
                                "matched": True,
                                "attempts": attempts,
                                "stable_match_count": config.stable_match_count,
                                "wait_timeout_seconds": config.timeout_seconds,
                                "elapsed_ms": elapsed_ms,
                                "request_source": config.read.connection.request_source,
                                "last_observed": last_result_value,
                            }
                        )
                    }
            else:
                consecutive_match_count = 0

            elapsed_seconds = time.perf_counter() - started_at
            if (
                config.timeout_seconds is not None
                and elapsed_seconds >= config.timeout_seconds
            ):
                raise OperationTimeoutError(
                    "Modbus wait-condition 等待超时",
                    details={
                        "node_id": request.node_id,
                        "node_name": node_name,
                        "host": config.read.connection.host,
                        "port": config.read.connection.port,
                        "unit_id": config.read.connection.unit_id,
                        "register_address": config.read.logical_address.raw_address,
                        "address_family": config.read.logical_address.family,
                        "data_type": config.read.data_type,
                        "operator": config.operator,
                        "expected_value": config.expected_value,
                        "attempts": attempts,
                        "timeout_seconds": config.timeout_seconds,
                        "last_observed": last_result_value,
                    },
                )
            time.sleep(config.poll_interval_ms / 1000.0)


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
    normalized_value = _normalize_json_value(raw_value, field_name="value", node_name=node_name)
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


def _build_wait_condition_config(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> ModbusWaitConditionConfig:
    """构造 wait-condition 配置。"""

    overrides = _read_request_overrides(request, node_name=node_name)
    read_config = _build_read_config(request=request, node_name=node_name)
    operator = _read_wait_operator(
        node_name=node_name,
        parameter_value=request.parameters.get("operator"),
        override_value=overrides.get("operator"),
    )
    expected_value = overrides.get("expected_value", request.parameters.get("expected_value"))
    if operator in {"eq", "ne", "gt", "ge", "lt", "le", "contains", "bitmask_any_set", "bitmask_all_set"}:
        if expected_value is None:
            raise InvalidRequestError(
                f"{node_name} 在当前 operator 下要求 expected_value 不能为空",
                details={"operator": operator},
            )
        expected_value = _normalize_json_value(
            expected_value,
            field_name="expected_value",
            node_name=node_name,
        )
    else:
        expected_value = None
    poll_interval_ms = _read_positive_int_parameter(
        field_name="poll_interval_ms",
        node_name=node_name,
        parameter_value=request.parameters.get("poll_interval_ms"),
        override_value=overrides.get("poll_interval_ms"),
        default_value=200,
    )
    timeout_seconds = _read_optional_positive_float_parameter(
        field_name="wait_timeout_seconds",
        node_name=node_name,
        parameter_present="wait_timeout_seconds" in request.parameters,
        parameter_value=request.parameters.get("wait_timeout_seconds"),
        override_present="wait_timeout_seconds" in overrides,
        override_value=overrides.get("wait_timeout_seconds"),
        default_value=60.0,
    )
    stable_match_count = _read_positive_int_parameter(
        field_name="stable_match_count",
        node_name=node_name,
        parameter_value=request.parameters.get("stable_match_count"),
        override_value=overrides.get("stable_match_count"),
        default_value=1,
    )
    return ModbusWaitConditionConfig(
        read=read_config,
        operator=operator,
        expected_value=expected_value,
        poll_interval_ms=poll_interval_ms,
        timeout_seconds=timeout_seconds,
        stable_match_count=stable_match_count,
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
        _raise_as_service_error(exc=exc, node_name=node_name, connection=config.connection)

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
        "address_family": config.logical_address.family,
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
            encoded_registers = _encode_register_values(config=config, node_name=node_name)
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
        _raise_as_service_error(exc=exc, node_name=node_name, connection=config.connection)

    return {
        "transport": "modbus-tcp",
        "operation": "write_value",
        "host": config.connection.host,
        "port": config.connection.port,
        "unit_id": config.connection.unit_id,
        "register_address": config.logical_address.raw_address,
        "address_family": config.logical_address.family,
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


def _decode_observed_value(
    *,
    config: ModbusReadConfig,
    raw_values: list[bool | int],
    node_name: str,
) -> object:
    """按节点 data_type 把原始返回解码成最终值。"""

    if config.data_type == "bool":
        if len(raw_values) != 1 or not isinstance(raw_values[0], bool):
            raise InvalidRequestError(f"{node_name} 读取 bool 时得到非法 bit 响应")
        return raw_values[0]
    if any(isinstance(item, bool) for item in raw_values):
        raise InvalidRequestError(f"{node_name} 当前地址类型不支持按 {config.data_type} 解码")
    registers = [int(item) for item in raw_values]
    if config.data_type == "uint8":
        return _decode_uint8(registers[0], byte_position=config.byte_position)
    if config.data_type == "int8":
        return _decode_int8(registers[0], byte_position=config.byte_position)
    if config.data_type == "uint16":
        return registers[0]
    if config.data_type == "int16":
        return _unpack_scalar(">h", _registers_to_bytes(registers=registers, word_order=config.word_order))
    if config.data_type == "uint32":
        return _unpack_scalar(">I", _registers_to_bytes(registers=registers, word_order=config.word_order))
    if config.data_type == "int32":
        return _unpack_scalar(">i", _registers_to_bytes(registers=registers, word_order=config.word_order))
    if config.data_type == "uint64":
        return _unpack_scalar(">Q", _registers_to_bytes(registers=registers, word_order=config.word_order))
    if config.data_type == "int64":
        return _unpack_scalar(">q", _registers_to_bytes(registers=registers, word_order=config.word_order))
    if config.data_type == "float":
        return _unpack_scalar(">f", _registers_to_bytes(registers=registers, word_order=config.word_order))
    if config.data_type == "double":
        return _unpack_scalar(">d", _registers_to_bytes(registers=registers, word_order=config.word_order))
    if config.data_type == "string":
        assert config.string_length is not None
        raw_bytes = _registers_to_bytes(registers=registers, word_order=config.word_order)
        payload_bytes = raw_bytes[: config.string_length]
        try:
            return payload_bytes.rstrip(b"\x00").decode(config.string_encoding)
        except Exception as exc:
            raise InvalidRequestError(
                f"{node_name} 无法按指定 string_encoding 解码字符串",
                details={
                    "string_encoding": config.string_encoding,
                    "raw_values": registers,
                    "error_message": str(exc),
                },
            ) from exc
    raise InvalidRequestError(f"{node_name} 不支持当前 data_type", details={"data_type": config.data_type})


def _resolve_register_count(
    *,
    config: ModbusReadConfig,
    node_name: str,
) -> int:
    """根据 data_type 推导所需寄存器数量。"""

    if config.data_type == "string":
        assert config.string_length is not None
        register_count = math.ceil(config.string_length / 2)
    else:
        register_count = _FIXED_REGISTER_COUNTS.get(config.data_type, 1)
    if register_count <= 0 or register_count > 125:
        raise InvalidRequestError(
            f"{node_name} 的 data_type 推导出非法寄存器数量",
            details={"data_type": config.data_type, "register_count": register_count},
        )
    return register_count


def _encode_register_values(
    *,
    config: ModbusWriteConfig,
    node_name: str,
) -> list[int]:
    """按 data_type 把输入值编码成 holding registers。"""

    data_type = config.data_type
    raw_value = config.value
    if data_type == "uint8":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=0,
            maximum=255,
        )
        if config.byte_position == "high":
            return [normalized << 8]
        return [normalized]
    if data_type == "int8":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=-128,
            maximum=127,
        )
        unsigned_value = normalized & 0xFF
        if config.byte_position == "high":
            return [unsigned_value << 8]
        return [unsigned_value]
    if data_type == "uint16":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=0,
            maximum=65535,
        )
        return [normalized]
    if data_type == "int16":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=-32768,
            maximum=32767,
        )
        return _bytes_to_registers(payload=struct.pack(">h", normalized), word_order=config.word_order)
    if data_type == "uint32":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=0,
            maximum=0xFFFFFFFF,
        )
        return _bytes_to_registers(payload=struct.pack(">I", normalized), word_order=config.word_order)
    if data_type == "int32":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=-(2**31),
            maximum=2**31 - 1,
        )
        return _bytes_to_registers(payload=struct.pack(">i", normalized), word_order=config.word_order)
    if data_type == "uint64":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=0,
            maximum=0xFFFFFFFFFFFFFFFF,
        )
        return _bytes_to_registers(payload=struct.pack(">Q", normalized), word_order=config.word_order)
    if data_type == "int64":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=-(2**63),
            maximum=2**63 - 1,
        )
        return _bytes_to_registers(payload=struct.pack(">q", normalized), word_order=config.word_order)
    if data_type == "float":
        normalized = _coerce_float_value(raw_value=raw_value, node_name=node_name, field_name="value")
        return _bytes_to_registers(payload=struct.pack(">f", normalized), word_order=config.word_order)
    if data_type == "double":
        normalized = _coerce_float_value(raw_value=raw_value, node_name=node_name, field_name="value")
        return _bytes_to_registers(payload=struct.pack(">d", normalized), word_order=config.word_order)
    if data_type == "string":
        if not isinstance(raw_value, str):
            raise InvalidRequestError(f"{node_name} 的 value 必须是字符串")
        try:
            encoded_bytes = raw_value.encode(config.string_encoding)
        except Exception as exc:
            raise InvalidRequestError(
                f"{node_name} 无法按指定 string_encoding 编码字符串",
                details={"string_encoding": config.string_encoding, "error_message": str(exc)},
            ) from exc
        target_length = config.string_length or len(encoded_bytes)
        if target_length <= 0:
            raise InvalidRequestError(f"{node_name} 的 string_length 必须大于 0")
        if len(encoded_bytes) > target_length:
            raise InvalidRequestError(
                f"{node_name} 的字符串长度超过 string_length",
                details={"string_length": target_length, "actual_length": len(encoded_bytes)},
            )
        padded_bytes = encoded_bytes.ljust(target_length, b"\x00")
        if len(padded_bytes) % 2 != 0:
            padded_bytes += b"\x00"
        return _bytes_to_registers(payload=padded_bytes, word_order=config.word_order)
    raise InvalidRequestError(f"{node_name} 不支持当前 data_type", details={"data_type": data_type})


def _registers_to_bytes(*, registers: list[int], word_order: WordOrder) -> bytes:
    """把寄存器列表按指定 word order 展平成字节序列。"""

    normalized_registers = list(registers)
    if word_order == "little":
        normalized_registers.reverse()
    return b"".join(struct.pack(">H", register_value) for register_value in normalized_registers)


def _bytes_to_registers(*, payload: bytes, word_order: WordOrder) -> list[int]:
    """把字节序列转成寄存器列表。"""

    if len(payload) % 2 != 0:
        raise InvalidRequestError("寄存器编码字节长度必须是偶数")
    register_count = len(payload) // 2
    registers = list(struct.unpack(f">{register_count}H", payload))
    if word_order == "little":
        registers.reverse()
    return registers


def _unpack_scalar(format_string: str, payload: bytes) -> object:
    """把固定长度字节序列解码成标量。"""

    return struct.unpack(format_string, payload)[0]


def _decode_uint8(register_value: int, *, byte_position: BytePosition) -> int:
    """从单个寄存器里抽取一个 uint8。"""

    if byte_position == "high":
        return (register_value >> 8) & 0xFF
    return register_value & 0xFF


def _decode_int8(register_value: int, *, byte_position: BytePosition) -> int:
    """从单个寄存器里抽取一个 int8。"""

    raw_value = _decode_uint8(register_value, byte_position=byte_position)
    if raw_value >= 0x80:
        return raw_value - 0x100
    return raw_value


def _evaluate_wait_condition(
    *,
    operator: WaitOperator,
    observed_value: object,
    expected_value: object | None,
    node_name: str,
) -> bool:
    """判断当前值是否满足等待条件。"""

    if operator in {"eq", "ne", "gt", "ge", "lt", "le"}:
        assert expected_value is not None
        return compare_values(
            left_value=observed_value,
            right_value=expected_value,
            operator=operator,
        )
    if operator == "contains":
        assert expected_value is not None
        if not isinstance(observed_value, str):
            raise InvalidRequestError(f"{node_name} 的 contains 只支持字符串 observed_value")
        if not isinstance(expected_value, str):
            raise InvalidRequestError(f"{node_name} 的 contains 要求 expected_value 也是字符串")
        return expected_value in observed_value
    if operator in {"bitmask_any_set", "bitmask_all_set"}:
        assert expected_value is not None
        if isinstance(observed_value, bool) or not isinstance(observed_value, int):
            raise InvalidRequestError(f"{node_name} 的 {operator} 要求 observed_value 必须是整数")
        if isinstance(expected_value, bool) or not isinstance(expected_value, int):
            raise InvalidRequestError(f"{node_name} 的 {operator} 要求 expected_value 必须是整数")
        if operator == "bitmask_any_set":
            return (observed_value & expected_value) != 0
        return (observed_value & expected_value) == expected_value
    raise InvalidRequestError(f"{node_name} 不支持当前 wait operator", details={"operator": operator})


def _open_modbus_client(
    connection: ModbusConnectionConfig,
    *,
    node_name: str,
) -> _ModbusClientContext:
    """创建并连接一个同步 Modbus TCP client。"""

    client = ProjectModbusTcpClient(
        connection.host,
        port=connection.port,
        timeout=connection.timeout_seconds,
        retries=connection.retries,
    )
    try:
        if not client.connect():
            raise ServiceError(
                "Modbus TCP 连接失败",
                code="modbus_connection_failed",
                status_code=502,
                details={
                    "node_name": node_name,
                    "host": connection.host,
                    "port": connection.port,
                    "unit_id": connection.unit_id,
                },
            )
    except Exception as exc:  # pragma: no cover - 由统一错误翻译兜底
        try:
            _raise_as_service_error(exc=exc, node_name=node_name, connection=connection)
        finally:
            client.close()
    return _ModbusClientContext(client)


class _ModbusClientContext:
    """为 ProjectModbusTcpClient 提供统一 close 包装。"""

    def __init__(self, client: ProjectModbusTcpClient) -> None:
        self._client = client

    def __enter__(self) -> ProjectModbusTcpClient:
        return self._client

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._client.close()


def _build_response_meta(
    response: ModbusBitsReadResponse | ModbusRegistersReadResponse | ModbusWriteResponse,
) -> dict[str, object]:
    """提取统一响应元数据。"""

    return {
        "dev_id": response.dev_id,
        "transaction_id": response.transaction_id,
        "function_code": response.function_code,
        "exception_code": response.exception_code,
        "retries": response.retries,
    }


def _raise_as_service_error(
    *,
    exc: Exception,
    node_name: str,
    connection: ModbusConnectionConfig,
) -> None:
    """把底层异常翻译为项目内错误。"""

    message = str(exc).strip() or exc.__class__.__name__
    if isinstance(exc, ModbusTcpTimeoutError):
        raise OperationTimeoutError(
            "Modbus TCP 设备响应超时",
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, ModbusTcpConnectionError):
        raise ServiceError(
            "Modbus TCP 连接失败",
            code="modbus_connection_failed",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, ModbusTcpDeviceError):
        raise ServiceError(
            "Modbus TCP 设备返回异常响应",
            code="modbus_device_exception",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "function_code": exc.function_code,
                "exception_code": exc.exception_code,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, ModbusTcpProtocolError):
        raise ServiceError(
            "Modbus TCP 响应报文非法",
            code="modbus_protocol_error",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, ModbusTcpError):
        raise ServiceError(
            "Modbus TCP 请求失败",
            code="modbus_request_failed",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, OSError):
        raise ServiceError(
            "Modbus TCP 套接字访问失败",
            code="modbus_socket_error",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    raise ServiceError(
        "Modbus TCP 节点执行失败",
        code="modbus_runtime_failed",
        status_code=500,
        details={
            "node_name": node_name,
            "host": connection.host,
            "port": connection.port,
            "unit_id": connection.unit_id,
            "error_type": exc.__class__.__name__,
            "error_message": message,
        },
    ) from exc


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


def _read_logical_address(
    *,
    field_name: str,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
) -> ModbusLogicalAddress:
    """读取并解析逻辑寄存器地址。"""

    raw_value = overrides.get(field_name, request.parameters.get(field_name))
    if isinstance(raw_value, bool) or not isinstance(raw_value, (str, int)):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串或整数")
    text_value = str(raw_value).strip()
    if not text_value or not text_value.isdigit():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是纯数字地址")
    integer_value = int(text_value)
    if integer_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须大于 0")
    if text_value.startswith("0") or integer_value < 10001:
        zero_based_address = integer_value - 1
        family: AddressFamily = "coil"
    elif text_value.startswith("1"):
        zero_based_address = _resolve_prefixed_zero_based_address(
            raw_address=integer_value,
            base_candidates=(100001, 10001),
            node_name=node_name,
            field_name=field_name,
        )
        family = "discrete_input"
    elif text_value.startswith("3"):
        zero_based_address = _resolve_prefixed_zero_based_address(
            raw_address=integer_value,
            base_candidates=(300001, 30001),
            node_name=node_name,
            field_name=field_name,
        )
        family = "input_register"
    elif text_value.startswith("4"):
        zero_based_address = _resolve_prefixed_zero_based_address(
            raw_address=integer_value,
            base_candidates=(400001, 40001),
            node_name=node_name,
            field_name=field_name,
        )
        family = "holding_register"
    else:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 只支持 0xxxx / 1xxxx / 3xxxx / 4xxxx 地址语义"
        )
    if zero_based_address < 0 or zero_based_address > 65535:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 超出当前实现支持范围",
            details={"register_address": text_value, "zero_based_address": zero_based_address},
        )
    return ModbusLogicalAddress(
        raw_address=text_value,
        family=family,
        zero_based_address=zero_based_address,
    )


def _resolve_prefixed_zero_based_address(
    *,
    raw_address: int,
    base_candidates: tuple[int, ...],
    node_name: str,
    field_name: str,
) -> int:
    """按常见 PLC 地址前缀解析 1-based 逻辑地址。"""

    for base_value in base_candidates:
        zero_based_address = raw_address - base_value
        if 0 <= zero_based_address <= 65535:
            return zero_based_address
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 不符合当前支持的前缀地址格式",
        details={"register_address": raw_address, "base_candidates": list(base_candidates)},
    )


def _read_data_type(
    *,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
) -> ValueDataType:
    """读取 data_type。"""

    raw_value = overrides.get("data_type", request.parameters.get("data_type"))
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 data_type 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "bool",
        "uint8",
        "int8",
        "uint16",
        "int16",
        "uint32",
        "int32",
        "uint64",
        "int64",
        "float",
        "double",
        "string",
    }:
        raise InvalidRequestError(
            f"{node_name} 的 data_type 不支持当前取值",
            details={"data_type": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _validate_read_type_for_address(
    *,
    logical_address: ModbusLogicalAddress,
    data_type: ValueDataType,
    node_name: str,
) -> None:
    """校验读取地址类型与 data_type 是否匹配。"""

    if logical_address.family in {"coil", "discrete_input"}:
        if data_type != "bool":
            raise InvalidRequestError(
                f"{node_name} 的 {logical_address.family} 地址只支持 bool",
                details={"register_address": logical_address.raw_address, "data_type": data_type},
            )
        return
    if data_type == "bool":
        raise InvalidRequestError(
            f"{node_name} 的寄存器地址不支持 bool，请使用 0xxxx / 1xxxx 地址",
            details={"register_address": logical_address.raw_address},
        )


def _validate_write_type_for_address(
    *,
    logical_address: ModbusLogicalAddress,
    data_type: ValueDataType,
    node_name: str,
) -> None:
    """校验写入地址类型与 data_type 是否匹配。"""

    if logical_address.family == "coil":
        if data_type != "bool":
            raise InvalidRequestError(
                f"{node_name} 的 coil 地址只支持 bool 写入",
                details={"register_address": logical_address.raw_address, "data_type": data_type},
            )
        return
    if logical_address.family != "holding_register":
        raise InvalidRequestError(
            f"{node_name} 当前只允许向 coil 或 holding register 写入",
            details={"register_address": logical_address.raw_address, "address_family": logical_address.family},
        )
    if data_type == "bool":
        raise InvalidRequestError(
            f"{node_name} 的 holding register 写入不支持 bool，请使用 0xxxx 地址",
            details={"register_address": logical_address.raw_address},
        )


def _read_string_length(
    *,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
    data_type: ValueDataType,
    required: bool,
) -> int | None:
    """读取 string_length。"""

    raw_value = overrides.get("string_length", request.parameters.get("string_length"))
    if raw_value is None:
        if required:
            raise InvalidRequestError(f"{node_name} 的 string data_type 要求 string_length 不能为空")
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 string_length 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 string_length 必须大于 0")
    if data_type != "string":
        raise InvalidRequestError(f"{node_name} 只有 string data_type 才允许设置 string_length")
    return raw_value


def _read_word_order(
    *,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
) -> WordOrder:
    """读取 word_order。"""

    raw_value = overrides.get("word_order", request.parameters.get("word_order"))
    if raw_value is None:
        return "big"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 word_order 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"big", "little"}:
        raise InvalidRequestError(f"{node_name} 的 word_order 仅支持 big 或 little")
    return normalized_value  # type: ignore[return-value]


def _read_byte_position(
    *,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
) -> BytePosition:
    """读取 byte_position。"""

    raw_value = overrides.get("byte_position", request.parameters.get("byte_position"))
    if raw_value is None:
        return "low"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 byte_position 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"low", "high"}:
        raise InvalidRequestError(f"{node_name} 的 byte_position 仅支持 low 或 high")
    return normalized_value  # type: ignore[return-value]


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
            str(key): _normalize_json_value(item, field_name=field_name, node_name=node_name)
            for key, item in raw_value.items()
        }
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 只支持 JSON 安全值",
        details={"value_type": raw_value.__class__.__name__},
    )
