"""PLC 寄存器 TriggerSource adapter。"""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, RLock, Thread
from typing import Literal

from backend.nodes.core_nodes.support.logic import compare_values
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.runtime.support.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)
from backend.service.application.workflows.trigger_sources.protocol_adapter import (
    WorkflowTriggerEventHandler,
)
from backend.service.application.workflows.trigger_sources.trigger_event_normalizer import (
    RawTriggerEvent,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.integrations.modbus.modbus_tcp_client import (
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
MatchOperator = Literal[
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
TriggerMode = Literal["enter-match"]
WordOrder = Literal["big", "little"]
BytePosition = Literal["low", "high"]

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
_INTEGER_VALUE_TYPES = {
    "uint8",
    "int8",
    "uint16",
    "int16",
    "uint32",
    "int32",
    "uint64",
    "int64",
}


@dataclass(frozen=True)
class ModbusConnectionConfig:
    """描述 TriggerSource 轮询使用的连接参数。"""

    host: str
    port: int
    unit_id: int
    timeout_seconds: float
    retries: int


@dataclass(frozen=True)
class ModbusLogicalAddress:
    """描述一条逻辑寄存器地址。"""

    raw_address: str
    family: AddressFamily
    zero_based_address: int


@dataclass(frozen=True)
class ModbusReadConfig:
    """描述单次寄存器读取配置。"""

    connection: ModbusConnectionConfig
    logical_address: ModbusLogicalAddress
    data_type: ValueDataType
    word_order: WordOrder
    byte_position: BytePosition
    string_length: int | None
    string_encoding: str


@dataclass(frozen=True)
class PlcRegisterMatchRuleConfig:
    """描述 PLC 触发匹配规则。"""

    operator: MatchOperator
    expected_value: object
    stable_match_count: int
    trigger_mode: TriggerMode
    cooldown_ms: int
    emit_initial_match: bool


@dataclass(frozen=True)
class PlcRegisterTriggerConfig:
    """描述单条 PLC TriggerSource 的最终配置。"""

    driver: str
    read: ModbusReadConfig
    poll_interval_ms: int
    reconnect_interval_ms: int
    match_rule: PlcRegisterMatchRuleConfig


@dataclass
class _PlcRegisterAdapterState:
    """描述单条 PLC TriggerSource 的运行状态。"""

    trigger_source_id: str
    config: PlcRegisterTriggerConfig
    stop_event: Event
    startup_event: Event = field(default_factory=Event)
    thread: Thread | None = None
    running: bool = False
    poll_count: SafeCounterState = field(default_factory=SafeCounterState)
    match_count: SafeCounterState = field(default_factory=SafeCounterState)
    submitted_count: SafeCounterState = field(default_factory=SafeCounterState)
    error_count: SafeCounterState = field(default_factory=SafeCounterState)
    timeout_count: SafeCounterState = field(default_factory=SafeCounterState)
    last_error: str | None = None
    startup_error: str | None = None
    last_polled_at: str | None = None
    last_match_at: str | None = None
    last_observed_value: object | None = None
    last_response_meta: dict[str, object] | None = None
    last_result_state: str | None = None
    sequence_id: int = 0
    consecutive_match_count: int = 0
    match_state_active: bool = False
    has_seen_non_match: bool = False
    last_emit_monotonic: float | None = None


class PlcRegisterTriggerAdapter:
    """通过 Modbus TCP 轮询 PLC 寄存器并提交 WorkflowRun。"""

    adapter_kind = "plc-register"

    def __init__(self, *, startup_timeout_seconds: float = 1.0) -> None:
        """初始化 PlcRegisterTriggerAdapter。"""

        if startup_timeout_seconds <= 0:
            raise InvalidRequestError("startup_timeout_seconds 必须大于 0")
        self.startup_timeout_seconds = startup_timeout_seconds
        self._states: dict[str, _PlcRegisterAdapterState] = {}
        self._lock = RLock()

    def start(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
    ) -> None:
        """启动一条 PLC TriggerSource 的后台轮询线程。"""

        if trigger_source.submit_mode != "async":
            raise InvalidRequestError(
                "plc-register 当前只支持 async submit_mode",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "submit_mode": trigger_source.submit_mode,
                },
            )
        config = _parse_trigger_config(trigger_source)
        stop_event = Event()
        state = _PlcRegisterAdapterState(
            trigger_source_id=trigger_source.trigger_source_id,
            config=config,
            stop_event=stop_event,
        )
        with self._lock:
            if trigger_source.trigger_source_id in self._states:
                raise InvalidRequestError(
                    "PLC TriggerSource 已经启动",
                    details={"trigger_source_id": trigger_source.trigger_source_id},
                )
            self._states[trigger_source.trigger_source_id] = state
        thread = Thread(
            target=self._poll_trigger_source,
            args=(trigger_source, event_handler, state),
            name=f"plc-register-trigger-{trigger_source.trigger_source_id}",
            daemon=True,
        )
        state.thread = thread
        thread.start()
        if not state.startup_event.wait(timeout=self.startup_timeout_seconds):
            self.stop(trigger_source_id=trigger_source.trigger_source_id)
            raise OperationTimeoutError(
                "等待 PLC TriggerSource 启动超时",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "timeout_seconds": self.startup_timeout_seconds,
                },
            )
        if state.startup_error is not None:
            with self._lock:
                self._states.pop(trigger_source.trigger_source_id, None)
            raise ServiceConfigurationError(
                "PLC TriggerSource 启动失败",
                details={
                    "trigger_source_id": trigger_source.trigger_source_id,
                    "error": state.startup_error,
                },
            )

    def stop(self, *, trigger_source_id: str) -> None:
        """停止一条 PLC TriggerSource。"""

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._lock:
            state = self._states.pop(normalized_trigger_source_id, None)
        if state is None:
            return
        state.stop_event.set()
        if state.thread is not None:
            state.thread.join(timeout=2.0)

    def get_health(self, *, trigger_source_id: str) -> dict[str, object]:
        """读取 PLC TriggerSource 的运行健康状态。"""

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._lock:
            state = self._states.get(normalized_trigger_source_id)
        if state is None:
            return {
                "adapter_kind": self.adapter_kind,
                "running": False,
                "trigger_source_id": normalized_trigger_source_id,
            }
        return {
            "adapter_kind": self.adapter_kind,
            "running": state.running,
            "trigger_source_id": normalized_trigger_source_id,
            "driver": state.config.driver,
            "host": state.config.read.connection.host,
            "port": state.config.read.connection.port,
            "unit_id": state.config.read.connection.unit_id,
            "register_address": state.config.read.logical_address.raw_address,
            "register_area": state.config.read.logical_address.family,
            "data_type": state.config.read.data_type,
            "poll_interval_ms": state.config.poll_interval_ms,
            "reconnect_interval_ms": state.config.reconnect_interval_ms,
            "operator": state.config.match_rule.operator,
            "expected_value": state.config.match_rule.expected_value,
            "stable_match_count": state.config.match_rule.stable_match_count,
            "trigger_mode": state.config.match_rule.trigger_mode,
            "cooldown_ms": state.config.match_rule.cooldown_ms,
            "emit_initial_match": state.config.match_rule.emit_initial_match,
            "last_error": state.last_error,
            "last_polled_at": state.last_polled_at,
            "last_match_at": state.last_match_at,
            "last_observed_value": _normalize_json_value(state.last_observed_value),
            "last_response_meta": dict(state.last_response_meta or {}),
            "last_result_state": state.last_result_state,
            "consecutive_match_count": state.consecutive_match_count,
            "match_state_active": state.match_state_active,
            **_counter_fields("poll_count", state.poll_count),
            **_counter_fields("match_count", state.match_count),
            **_counter_fields("submitted_count", state.submitted_count),
            **_counter_fields("error_count", state.error_count),
            **_counter_fields("timeout_count", state.timeout_count),
        }

    def _poll_trigger_source(
        self,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
        state: _PlcRegisterAdapterState,
    ) -> None:
        """执行后台轮询循环。"""

        client = ProjectModbusTcpClient(
            state.config.read.connection.host,
            port=state.config.read.connection.port,
            timeout=state.config.read.connection.timeout_seconds,
            retries=state.config.read.connection.retries,
        )
        try:
            state.running = True
            state.startup_event.set()
            while not state.stop_event.is_set():
                try:
                    self._poll_once(
                        trigger_source=trigger_source,
                        event_handler=event_handler,
                        state=state,
                        client=client,
                    )
                    if state.stop_event.wait(
                        state.config.poll_interval_ms / 1000.0
                    ):
                        break
                except Exception as error:  # pragma: no cover - 轮询线程异常由 health 暴露
                    _record_adapter_error(state, error)
                    client.close()
                    if state.stop_event.wait(
                        state.config.reconnect_interval_ms / 1000.0
                    ):
                        break
        except Exception as error:  # pragma: no cover - 启动阶段异常极少
            state.startup_error = str(error).strip() or error.__class__.__name__
            state.startup_event.set()
            _record_adapter_error(state, error)
        finally:
            state.running = False
            client.close()

    def _poll_once(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        event_handler: WorkflowTriggerEventHandler,
        state: _PlcRegisterAdapterState,
        client: ProjectModbusTcpClient,
    ) -> None:
        """执行一次轮询与匹配判断。"""

        previous_observed_value = state.last_observed_value
        read_result = _perform_read_operation(
            client=client,
            config=state.config.read,
            source_name=self.adapter_kind,
        )
        increment_safe_counter(state.poll_count)
        state.last_polled_at = _now_isoformat()
        state.last_observed_value = read_result["observed_value"]
        response_meta = read_result.get("response_meta")
        state.last_response_meta = (
            dict(response_meta) if isinstance(response_meta, dict) else None
        )
        matched = _evaluate_match_rule(
            operator=state.config.match_rule.operator,
            observed_value=read_result["observed_value"],
            expected_value=state.config.match_rule.expected_value,
            source_name=self.adapter_kind,
        )
        if matched:
            state.consecutive_match_count += 1
        else:
            state.consecutive_match_count = 0
            state.match_state_active = False
            state.has_seen_non_match = True
            return
        if state.consecutive_match_count < state.config.match_rule.stable_match_count:
            return
        if state.match_state_active:
            return
        state.match_state_active = True
        if not state.config.match_rule.emit_initial_match and not state.has_seen_non_match:
            return
        if not _cooldown_allows(state=state, cooldown_ms=state.config.match_rule.cooldown_ms):
            return
        increment_safe_counter(state.match_count)
        state.last_match_at = _now_isoformat()
        state.last_emit_monotonic = time.monotonic()
        raw_event = _build_raw_event(
            trigger_source=trigger_source,
            state=state,
            config=state.config,
            read_result=read_result,
            previous_observed_value=previous_observed_value,
        )
        result = event_handler.handle_trigger_event(
            trigger_source=trigger_source,
            raw_event=raw_event,
        )
        increment_safe_counter(state.submitted_count)
        _record_trigger_result(state, result)


def _parse_trigger_config(
    trigger_source: WorkflowTriggerSource,
) -> PlcRegisterTriggerConfig:
    """把 TriggerSource 配置解析为 PLC 轮询配置。"""

    transport_config = dict(trigger_source.transport_config)
    match_rule = dict(trigger_source.match_rule)
    driver = _read_text_choice(
        value=transport_config.get("driver"),
        field_name="transport_config.driver",
        allowed_values={"modbus-tcp"},
        default_value="modbus-tcp",
    )
    connection = ModbusConnectionConfig(
        host=_read_required_text(
            transport_config.get("host"), "transport_config.host"
        ),
        port=_read_positive_int(
            transport_config.get("port"),
            "transport_config.port",
            default_value=502,
            maximum=65535,
        ),
        unit_id=_read_positive_int(
            transport_config.get("unit_id"),
            "transport_config.unit_id",
            default_value=1,
            maximum=255,
        ),
        timeout_seconds=_read_positive_float(
            transport_config.get("timeout_seconds"),
            "transport_config.timeout_seconds",
            default_value=3.0,
        ),
        retries=_read_non_negative_int(
            transport_config.get("retries"),
            "transport_config.retries",
            default_value=1,
        ),
    )
    logical_address = _parse_logical_address(
        transport_config.get("register_address"),
        field_name="transport_config.register_address",
    )
    data_type = _read_data_type(transport_config.get("data_type"))
    _validate_read_type_for_address(
        logical_address=logical_address,
        data_type=data_type,
    )
    word_order = _read_word_order(transport_config.get("word_order"))
    byte_position = _read_byte_position(transport_config.get("byte_position"))
    string_length = _read_string_length(
        raw_value=transport_config.get("string_length"),
        data_type=data_type,
    )
    string_encoding = _read_optional_non_empty_text(
        transport_config.get("string_encoding"),
        field_name="transport_config.string_encoding",
        default_value="utf-8",
    )
    read_config = ModbusReadConfig(
        connection=connection,
        logical_address=logical_address,
        data_type=data_type,
        word_order=word_order,
        byte_position=byte_position,
        string_length=string_length,
        string_encoding=string_encoding,
    )
    operator = _read_match_operator(match_rule.get("operator"))
    expected_value = match_rule.get("expected_value")
    if expected_value is None:
        raise InvalidRequestError("match_rule.expected_value 不能为空")
    normalized_expected_value = _normalize_json_value(expected_value)
    _validate_match_rule_against_data_type(
        operator=operator,
        expected_value=normalized_expected_value,
        data_type=data_type,
    )
    return PlcRegisterTriggerConfig(
        driver=driver,
        read=read_config,
        poll_interval_ms=_read_positive_int(
            transport_config.get("poll_interval_ms"),
            "transport_config.poll_interval_ms",
            default_value=200,
        ),
        reconnect_interval_ms=_read_positive_int(
            transport_config.get("reconnect_interval_ms"),
            "transport_config.reconnect_interval_ms",
            default_value=1000,
        ),
        match_rule=PlcRegisterMatchRuleConfig(
            operator=operator,
            expected_value=normalized_expected_value,
            stable_match_count=_read_positive_int(
                match_rule.get("stable_match_count"),
                "match_rule.stable_match_count",
                default_value=1,
            ),
            trigger_mode=_read_trigger_mode(match_rule.get("trigger_mode")),
            cooldown_ms=_read_non_negative_int(
                match_rule.get("cooldown_ms"),
                "match_rule.cooldown_ms",
                default_value=0,
            ),
            emit_initial_match=_read_bool(
                match_rule.get("emit_initial_match"),
                "match_rule.emit_initial_match",
                default_value=False,
            ),
        ),
    )


def _perform_read_operation(
    *,
    client: ProjectModbusTcpClient,
    config: ModbusReadConfig,
    source_name: str,
) -> dict[str, object]:
    """执行一次读取并规整返回值。"""

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
            register_count = _resolve_register_count(config=config, source_name=source_name)
            response = client.read_input_registers(
                config.logical_address.zero_based_address,
                count=register_count,
                device_id=config.connection.unit_id,
            )
            raw_values = [int(item) for item in response.registers]
        else:
            register_count = _resolve_register_count(config=config, source_name=source_name)
            response = client.read_holding_registers(
                config.logical_address.zero_based_address,
                count=register_count,
                device_id=config.connection.unit_id,
            )
            raw_values = [int(item) for item in response.registers]
    except Exception as exc:  # pragma: no cover - 由统一错误翻译兜底
        _raise_as_service_error(
            exc=exc,
            source_name=source_name,
            connection=config.connection,
        )
    observed_value = _decode_observed_value(
        config=config,
        raw_values=raw_values,
        source_name=source_name,
    )
    return {
        "transport": "modbus-tcp",
        "operation": "plc_register_poll",
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
        "response_meta": _build_response_meta(response),
    }


def _decode_observed_value(
    *,
    config: ModbusReadConfig,
    raw_values: list[bool | int],
    source_name: str,
) -> object:
    """按 data_type 把原始寄存器值解码为最终值。"""

    if config.data_type == "bool":
        if len(raw_values) != 1 or not isinstance(raw_values[0], bool):
            raise InvalidRequestError(f"{source_name} 读取 bool 时得到非法 bit 响应")
        return raw_values[0]
    if any(isinstance(item, bool) for item in raw_values):
        raise InvalidRequestError(
            f"{source_name} 当前地址类型不支持按 {config.data_type} 解码"
        )
    registers = [int(item) for item in raw_values]
    if config.data_type == "uint8":
        return _decode_uint8(registers[0], byte_position=config.byte_position)
    if config.data_type == "int8":
        return _decode_int8(registers[0], byte_position=config.byte_position)
    if config.data_type == "uint16":
        return registers[0]
    if config.data_type == "int16":
        return _unpack_scalar(
            ">h",
            _registers_to_bytes(
                registers=registers,
                word_order=config.word_order,
            ),
        )
    if config.data_type == "uint32":
        return _unpack_scalar(
            ">I",
            _registers_to_bytes(
                registers=registers,
                word_order=config.word_order,
            ),
        )
    if config.data_type == "int32":
        return _unpack_scalar(
            ">i",
            _registers_to_bytes(
                registers=registers,
                word_order=config.word_order,
            ),
        )
    if config.data_type == "uint64":
        return _unpack_scalar(
            ">Q",
            _registers_to_bytes(
                registers=registers,
                word_order=config.word_order,
            ),
        )
    if config.data_type == "int64":
        return _unpack_scalar(
            ">q",
            _registers_to_bytes(
                registers=registers,
                word_order=config.word_order,
            ),
        )
    if config.data_type == "float":
        return _unpack_scalar(
            ">f",
            _registers_to_bytes(
                registers=registers,
                word_order=config.word_order,
            ),
        )
    if config.data_type == "double":
        return _unpack_scalar(
            ">d",
            _registers_to_bytes(
                registers=registers,
                word_order=config.word_order,
            ),
        )
    if config.data_type == "string":
        assert config.string_length is not None
        raw_bytes = _registers_to_bytes(
            registers=registers,
            word_order=config.word_order,
        )
        payload_bytes = raw_bytes[: config.string_length]
        try:
            return payload_bytes.rstrip(b"\x00").decode(config.string_encoding)
        except Exception as exc:
            raise InvalidRequestError(
                f"{source_name} 无法按指定 string_encoding 解码字符串",
                details={
                    "string_encoding": config.string_encoding,
                    "raw_values": registers,
                    "error_message": str(exc),
                },
            ) from exc
    raise InvalidRequestError(
        f"{source_name} 不支持当前 data_type",
        details={"data_type": config.data_type},
    )


def _resolve_register_count(*, config: ModbusReadConfig, source_name: str) -> int:
    """根据 data_type 推导读取寄存器数量。"""

    if config.data_type == "string":
        assert config.string_length is not None
        register_count = math.ceil(config.string_length / 2)
    else:
        register_count = _FIXED_REGISTER_COUNTS.get(config.data_type, 1)
    if register_count <= 0 or register_count > 125:
        raise InvalidRequestError(
            f"{source_name} 的 data_type 推导出非法寄存器数量",
            details={
                "data_type": config.data_type,
                "register_count": register_count,
            },
        )
    return register_count


def _evaluate_match_rule(
    *,
    operator: MatchOperator,
    observed_value: object,
    expected_value: object,
    source_name: str,
) -> bool:
    """判断当前观测值是否命中触发规则。"""

    if operator in {"eq", "ne", "gt", "ge", "lt", "le"}:
        return compare_values(
            left_value=observed_value,
            right_value=expected_value,
            operator=operator,
        )
    if operator == "contains":
        if not isinstance(observed_value, str):
            raise InvalidRequestError(
                f"{source_name} 的 contains 只支持字符串 observed_value"
            )
        if not isinstance(expected_value, str):
            raise InvalidRequestError(
                f"{source_name} 的 contains 要求 expected_value 也是字符串"
            )
        return expected_value in observed_value
    if operator in {"bitmask_any_set", "bitmask_all_set"}:
        if isinstance(observed_value, bool) or not isinstance(observed_value, int):
            raise InvalidRequestError(
                f"{source_name} 的 {operator} 要求 observed_value 必须是整数"
            )
        if isinstance(expected_value, bool) or not isinstance(expected_value, int):
            raise InvalidRequestError(
                f"{source_name} 的 {operator} 要求 expected_value 必须是整数"
            )
        if operator == "bitmask_any_set":
            return (observed_value & expected_value) != 0
        return (observed_value & expected_value) == expected_value
    raise InvalidRequestError(
        f"{source_name} 不支持当前匹配运算符",
        details={"operator": operator},
    )


def _cooldown_allows(*, state: _PlcRegisterAdapterState, cooldown_ms: int) -> bool:
    """判断当前匹配事件是否通过 cooldown 限制。"""

    if cooldown_ms <= 0:
        return True
    if state.last_emit_monotonic is None:
        return True
    return (time.monotonic() - state.last_emit_monotonic) * 1000.0 >= cooldown_ms


def _build_raw_event(
    *,
    trigger_source: WorkflowTriggerSource,
    state: _PlcRegisterAdapterState,
    config: PlcRegisterTriggerConfig,
    read_result: dict[str, object],
    previous_observed_value: object | None,
) -> RawTriggerEvent:
    """把一次命中的 PLC 轮询结果转换为 RawTriggerEvent。"""

    sequence_id = state.sequence_id + 1
    state.sequence_id = sequence_id
    occurred_at = _now_isoformat()
    payload = {
        "sequence_id": sequence_id,
        "occurred_at": occurred_at,
        "observed_value": _normalize_json_value(read_result["observed_value"]),
        "previous_observed_value": _normalize_json_value(previous_observed_value),
        "matched": True,
        "operator": config.match_rule.operator,
        "expected_value": _normalize_json_value(config.match_rule.expected_value),
        "stable_match_count": config.match_rule.stable_match_count,
        "trigger_mode": config.match_rule.trigger_mode,
        "register_address": read_result["register_address"],
        "register_area": read_result["register_area"],
        "zero_based_address": read_result["zero_based_address"],
        "data_type": read_result["data_type"],
        "host": read_result["host"],
        "port": read_result["port"],
        "unit_id": read_result["unit_id"],
        "response_meta": dict(read_result.get("response_meta") or {}),
    }
    metadata = {
        "transport": "modbus-tcp",
        "driver": config.driver,
        "poll_interval_ms": config.poll_interval_ms,
        "trigger_mode": config.match_rule.trigger_mode,
    }
    return RawTriggerEvent(
        event_id=f"{trigger_source.trigger_source_id}:{sequence_id}",
        trace_id=f"plc-register-{trigger_source.trigger_source_id}-{sequence_id}",
        occurred_at=occurred_at,
        payload=payload,
        metadata=metadata,
    )


def _record_trigger_result(
    state: _PlcRegisterAdapterState,
    result,
) -> None:
    """把 TriggerResult 摘要写回 adapter 状态。"""

    state.last_result_state = result.state
    if result.state == "timed_out":
        increment_safe_counter(state.timeout_count)
        state.last_error = result.error_message
        return
    if result.state == "failed":
        increment_safe_counter(state.error_count)
        state.last_error = result.error_message
        return
    state.last_error = None


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
    source_name: str,
    connection: ModbusConnectionConfig,
) -> None:
    """把底层 Modbus 异常翻译为项目内错误。"""

    message = str(exc).strip() or exc.__class__.__name__
    if isinstance(exc, ModbusTcpTimeoutError):
        raise OperationTimeoutError(
            "Modbus TCP 设备响应超时",
            details={
                "source_name": source_name,
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
                "source_name": source_name,
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
                "source_name": source_name,
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
                "source_name": source_name,
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
                "source_name": source_name,
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
                "source_name": source_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    raise ServiceError(
        "Modbus TCP TriggerSource 执行失败",
        code="modbus_trigger_runtime_failed",
        status_code=500,
        details={
            "source_name": source_name,
            "host": connection.host,
            "port": connection.port,
            "unit_id": connection.unit_id,
            "error_type": exc.__class__.__name__,
            "error_message": message,
        },
    ) from exc


def _record_adapter_error(state: _PlcRegisterAdapterState, error: Exception) -> None:
    """记录 adapter 错误计数和最近错误。"""

    if isinstance(error, OperationTimeoutError):
        increment_safe_counter(state.timeout_count)
        state.last_error = error.message
        return
    increment_safe_counter(state.error_count)
    state.last_error = (
        error.message if isinstance(error, ServiceError) else error.__class__.__name__
    )


def _counter_fields(prefix: str, counter: SafeCounterState) -> dict[str, int]:
    """把 SafeCounterState 转换为统一计数字段。"""

    snapshot = snapshot_safe_counter(counter)
    return {
        prefix: snapshot["value"],
        f"{prefix}_rollover_count": snapshot["rollover_count"],
    }


def _parse_logical_address(raw_value: object, *, field_name: str) -> ModbusLogicalAddress:
    """按 PLC 常用前缀语义解析逻辑寄存器地址。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (str, int)):
        raise InvalidRequestError(f"{field_name} 必须是字符串或整数")
    text_value = str(raw_value).strip()
    if not text_value or not text_value.isdigit():
        raise InvalidRequestError(f"{field_name} 必须是纯数字地址")
    integer_value = int(text_value)
    if integer_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    if text_value.startswith("0") or integer_value < 10001:
        zero_based_address = integer_value - 1
        family: AddressFamily = "coil"
    elif text_value.startswith("1"):
        zero_based_address = _resolve_prefixed_zero_based_address(
            raw_address=integer_value,
            base_candidates=(100001, 10001),
            field_name=field_name,
        )
        family = "discrete_input"
    elif text_value.startswith("3"):
        zero_based_address = _resolve_prefixed_zero_based_address(
            raw_address=integer_value,
            base_candidates=(300001, 30001),
            field_name=field_name,
        )
        family = "input_register"
    elif text_value.startswith("4"):
        zero_based_address = _resolve_prefixed_zero_based_address(
            raw_address=integer_value,
            base_candidates=(400001, 40001),
            field_name=field_name,
        )
        family = "holding_register"
    else:
        raise InvalidRequestError(
            f"{field_name} 只支持 0xxxx / 1xxxx / 3xxxx / 4xxxx 地址语义"
        )
    if zero_based_address < 0 or zero_based_address > 65535:
        raise InvalidRequestError(
            f"{field_name} 超出当前实现支持范围",
            details={
                "register_address": text_value,
                "zero_based_address": zero_based_address,
            },
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
    field_name: str,
) -> int:
    """按常见 PLC 前缀把逻辑地址转换为 zero-based 偏移。"""

    for base_value in base_candidates:
        zero_based_address = raw_address - base_value
        if 0 <= zero_based_address <= 65535:
            return zero_based_address
    raise InvalidRequestError(
        f"{field_name} 不符合当前支持的前缀地址格式",
        details={
            "register_address": raw_address,
            "base_candidates": list(base_candidates),
        },
    )


def _read_data_type(raw_value: object) -> ValueDataType:
    """读取 data_type。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError("transport_config.data_type 必须是字符串")
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
            "transport_config.data_type 不支持当前取值",
            details={"data_type": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _validate_read_type_for_address(
    *,
    logical_address: ModbusLogicalAddress,
    data_type: ValueDataType,
) -> None:
    """校验地址类型与 data_type 是否匹配。"""

    if logical_address.family in {"coil", "discrete_input"}:
        if data_type != "bool":
            raise InvalidRequestError(
                f"{logical_address.family} 地址只支持 bool",
                details={
                    "register_address": logical_address.raw_address,
                    "data_type": data_type,
                },
            )
        return
    if data_type == "bool":
        raise InvalidRequestError(
            "寄存器地址不支持 bool，请使用 0xxxx / 1xxxx 地址",
            details={"register_address": logical_address.raw_address},
        )


def _validate_match_rule_against_data_type(
    *,
    operator: MatchOperator,
    expected_value: object,
    data_type: ValueDataType,
) -> None:
    """校验匹配规则与 data_type 的组合是否合法。"""

    if operator == "contains" and data_type != "string":
        raise InvalidRequestError("contains 只支持 string data_type")
    if operator in {"bitmask_any_set", "bitmask_all_set"} and data_type not in _INTEGER_VALUE_TYPES:
        raise InvalidRequestError(
            f"{operator} 只支持整数 data_type",
            details={"data_type": data_type},
        )
    if data_type == "bool" and operator not in {"eq", "ne"}:
        raise InvalidRequestError(
            "bool data_type 只支持 eq / ne 匹配",
            details={"operator": operator},
        )
    if operator == "contains" and not isinstance(expected_value, str):
        raise InvalidRequestError("contains 要求 expected_value 必须是字符串")
    if operator in {"bitmask_any_set", "bitmask_all_set"} and (
        isinstance(expected_value, bool) or not isinstance(expected_value, int)
    ):
        raise InvalidRequestError(
            f"{operator} 要求 expected_value 必须是整数",
            details={"expected_value_type": expected_value.__class__.__name__},
        )


def _read_string_length(raw_value: object, *, data_type: ValueDataType) -> int | None:
    """读取 string_length。"""

    if raw_value is None:
        if data_type == "string":
            raise InvalidRequestError(
                "string data_type 要求 transport_config.string_length 不能为空"
            )
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("transport_config.string_length 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError("transport_config.string_length 必须大于 0")
    if data_type != "string":
        raise InvalidRequestError("只有 string data_type 才允许设置 string_length")
    return raw_value


def _read_word_order(raw_value: object) -> WordOrder:
    """读取 word_order。"""

    if raw_value is None:
        return "big"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("transport_config.word_order 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"big", "little"}:
        raise InvalidRequestError("transport_config.word_order 仅支持 big 或 little")
    return normalized_value  # type: ignore[return-value]


def _read_byte_position(raw_value: object) -> BytePosition:
    """读取 byte_position。"""

    if raw_value is None:
        return "low"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("transport_config.byte_position 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"low", "high"}:
        raise InvalidRequestError(
            "transport_config.byte_position 仅支持 low 或 high"
        )
    return normalized_value  # type: ignore[return-value]


def _read_match_operator(raw_value: object) -> MatchOperator:
    """读取匹配运算符。"""

    if raw_value is None:
        return "eq"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("match_rule.operator 必须是字符串")
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
            "match_rule.operator 不支持当前取值",
            details={"operator": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_trigger_mode(raw_value: object) -> TriggerMode:
    """读取 trigger_mode。"""

    if raw_value is None:
        return "enter-match"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("match_rule.trigger_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value != "enter-match":
        raise InvalidRequestError(
            "plc-register 当前只支持 enter-match trigger_mode",
            details={"trigger_mode": raw_value},
        )
    return "enter-match"


def _read_required_text(raw_value: object, field_name: str) -> str:
    """读取必填非空字符串。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_optional_non_empty_text(
    raw_value: object,
    *,
    field_name: str,
    default_value: str,
) -> str:
    """读取可选非空字符串。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_text_choice(
    *,
    value: object,
    field_name: str,
    allowed_values: set[str],
    default_value: str,
) -> str:
    """读取带默认值的枚举文本字段。"""

    if value is None:
        return default_value
    if not isinstance(value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = value.strip().lower()
    if normalized_value not in allowed_values:
        raise InvalidRequestError(
            f"{field_name} 不支持当前取值",
            details={
                field_name: normalized_value,
                "allowed_values": sorted(allowed_values),
            },
        )
    return normalized_value


def _read_positive_int(
    raw_value: object,
    field_name: str,
    *,
    default_value: int,
    maximum: int | None = None,
) -> int:
    """读取正整数参数。"""

    if raw_value is None:
        normalized_value = default_value
    else:
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise InvalidRequestError(f"{field_name} 必须是整数")
        normalized_value = raw_value
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    if maximum is not None and normalized_value > maximum:
        raise InvalidRequestError(
            f"{field_name} 超出允许范围",
            details={"maximum": maximum, "actual": normalized_value},
        )
    return normalized_value


def _read_non_negative_int(
    raw_value: object,
    field_name: str,
    *,
    default_value: int,
) -> int:
    """读取非负整数参数。"""

    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{field_name} 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return raw_value


def _read_positive_float(
    raw_value: object,
    field_name: str,
    *,
    default_value: float,
) -> float:
    """读取正数参数。"""

    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数字")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value


def _read_bool(raw_value: object, field_name: str, *, default_value: bool) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _normalize_json_value(value: object) -> object:
    """把值递归规范化为 JSON 安全结构。"""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_json_value(item)
            for key, item in value.items()
        }
    raise InvalidRequestError(
        "plc-register 只支持 JSON 安全值",
        details={"value_type": value.__class__.__name__},
    )


def _registers_to_bytes(*, registers: list[int], word_order: WordOrder) -> bytes:
    """把寄存器列表按指定 word order 展平成字节序列。"""

    normalized_registers = list(registers)
    if word_order == "little":
        normalized_registers.reverse()
    return b"".join(
        struct.pack(">H", register_value) for register_value in normalized_registers
    )


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


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized_value


def _now_isoformat() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
