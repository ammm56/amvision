"""PLC Modbus TCP 节点共享运行时适配层。"""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass
from typing import Literal

from backend.nodes.core_nodes._inspection_record_node_support import (
    require_alarm_record_payload,
    require_ok_ng_value,
)
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
from backend.service.infrastructure.integrations.modbus import (
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
SignalSourceScope = Literal["result", "alarm", "request", "literal"]

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

_MISSING_SOURCE_VALUE = object()


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


@dataclass(frozen=True)
class ModbusSignalMappingConfig:
    """描述单个结果回写信号映射。"""

    signal_name: str
    enabled: bool
    source_scope: SignalSourceScope
    source_path: str | None
    logical_address: ModbusLogicalAddress
    data_type: ValueDataType
    literal_value: object | None
    true_value: object | None
    false_value: object | None
    word_order: WordOrder
    byte_position: BytePosition
    string_length: int | None
    string_encoding: str
    skip_when_missing: bool


@dataclass(frozen=True)
class ModbusWriteResultSignalsConfig:
    """描述结果回写节点最终配置。"""

    connection: ModbusConnectionConfig
    continue_on_error: bool
    mappings: tuple[ModbusSignalMappingConfig, ...]
    request_signal_values: dict[str, object]
    disabled_signals: frozenset[str]


@dataclass(frozen=True)
class ResolvedSignalValue:
    """描述单个信号的最终写入值或跳过原因。"""

    signal_name: str
    source_scope: SignalSourceScope
    source_path: str | None
    source_label: str
    value: object | None
    skip_reason: str | None


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
                                "register_area": config.read.logical_address.family,
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
                        "register_area": config.read.logical_address.family,
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
        raw_value=overrides.get("default_word_order", request.parameters.get("default_word_order")),
        node_name=node_name,
        field_name="default_word_order",
        default_value="big",
    )
    default_byte_position = _read_named_byte_position(
        raw_value=overrides.get("default_byte_position", request.parameters.get("default_byte_position")),
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
        raise InvalidRequestError(f"{node_name} 的 {field_prefix}.literal_value 不能为空")
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
            details={"source_scope": mapping.source_scope, "source_path": mapping.source_path},
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


def _require_result_record_payload(
    raw_payload: object,
    *,
    field_name: str,
    node_name: str,
) -> dict[str, object]:
    """校验结果对象输入。"""

    if not isinstance(raw_payload, dict):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 输入必须是 result-record 对象")
    ok_ng = require_ok_ng_value(raw_payload.get("ok_ng"), field_name=f"{field_name}.ok_ng")
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
        if not isinstance(current_value, dict) or normalized_segment not in current_value:
            return _MISSING_SOURCE_VALUE
        current_value = current_value[normalized_segment]
    return current_value


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


def _read_logical_address(
    *,
    field_name: str,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
) -> ModbusLogicalAddress:
    """读取并解析逻辑寄存器地址。"""

    return _parse_logical_address_value(
        raw_value=overrides.get(field_name, request.parameters.get(field_name)),
        field_name=field_name,
        node_name=node_name,
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


def _parse_logical_address_value(
    *,
    raw_value: object,
    field_name: str,
    node_name: str,
) -> ModbusLogicalAddress:
    """把原始地址值解析成逻辑地址对象。"""

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


def _read_data_type(
    *,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
) -> ValueDataType:
    """读取 data_type。"""

    return _parse_data_type_value(
        raw_value=overrides.get("data_type", request.parameters.get("data_type")),
        field_name="data_type",
        node_name=node_name,
    )


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
            details={"register_address": logical_address.raw_address, "register_area": logical_address.family},
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

    return _parse_string_length_value(
        raw_value=overrides.get("string_length", request.parameters.get("string_length")),
        field_name="string_length",
        node_name=node_name,
        data_type=data_type,
        required=required,
    )


def _read_word_order(
    *,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
) -> WordOrder:
    """读取 word_order。"""

    return _read_named_word_order(
        raw_value=overrides.get("word_order", request.parameters.get("word_order")),
        node_name=node_name,
        field_name="word_order",
        default_value="big",
    )


def _read_byte_position(
    *,
    request: WorkflowNodeExecutionRequest,
    overrides: dict[str, object],
    node_name: str,
) -> BytePosition:
    """读取 byte_position。"""

    return _read_named_byte_position(
        raw_value=overrides.get("byte_position", request.parameters.get("byte_position")),
        node_name=node_name,
        field_name="byte_position",
        default_value="low",
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


def _parse_data_type_value(
    *,
    raw_value: object,
    field_name: str,
    node_name: str,
) -> ValueDataType:
    """把原始 data_type 规整为受支持的枚举值。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
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
            f"{node_name} 的 {field_name} 不支持当前取值",
            details={"data_type": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _parse_string_length_value(
    *,
    raw_value: object,
    field_name: str,
    node_name: str,
    data_type: ValueDataType,
    required: bool,
) -> int | None:
    """把原始 string_length 规整为合法字节长度。"""

    if raw_value is None:
        if required:
            raise InvalidRequestError(f"{node_name} 的 string data_type 要求 {field_name} 不能为空")
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须大于 0")
    if data_type != "string":
        raise InvalidRequestError(f"{node_name} 只有 string data_type 才允许设置 {field_name}")
    return raw_value


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
            str(key): _normalize_json_value(item, field_name=field_name, node_name=node_name)
            for key, item in raw_value.items()
        }
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 只支持 JSON 安全值",
        details={"value_type": raw_value.__class__.__name__},
    )
