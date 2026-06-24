"""PLC Modbus TCP runtime 使用的类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
