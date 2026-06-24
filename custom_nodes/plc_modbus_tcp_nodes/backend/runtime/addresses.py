"""PLC Modbus TCP 逻辑地址与 data_type 校验。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _read_named_byte_position,
    _read_named_word_order,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    AddressFamily,
    BytePosition,
    ModbusLogicalAddress,
    ValueDataType,
    WordOrder,
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
        details={
            "register_address": raw_address,
            "base_candidates": list(base_candidates),
        },
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
                details={
                    "register_address": logical_address.raw_address,
                    "data_type": data_type,
                },
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
                details={
                    "register_address": logical_address.raw_address,
                    "data_type": data_type,
                },
            )
        return
    if logical_address.family != "holding_register":
        raise InvalidRequestError(
            f"{node_name} 当前只允许向 coil 或 holding register 写入",
            details={
                "register_address": logical_address.raw_address,
                "register_area": logical_address.family,
            },
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
        raw_value=overrides.get(
            "string_length", request.parameters.get("string_length")
        ),
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
        raw_value=overrides.get(
            "byte_position", request.parameters.get("byte_position")
        ),
        node_name=node_name,
        field_name="byte_position",
        default_value="low",
    )


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
            raise InvalidRequestError(
                f"{node_name} 的 string data_type 要求 {field_name} 不能为空"
            )
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须大于 0")
    if data_type != "string":
        raise InvalidRequestError(
            f"{node_name} 只有 string data_type 才允许设置 {field_name}"
        )
    return raw_value
