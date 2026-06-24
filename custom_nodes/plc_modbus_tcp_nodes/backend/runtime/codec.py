"""PLC Modbus TCP 寄存器编解码。"""

from __future__ import annotations

import math
import struct

from backend.service.application.errors import InvalidRequestError
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _coerce_float_value,
    _coerce_int_value,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    BytePosition,
    ModbusReadConfig,
    ModbusWriteConfig,
    ValueDataType,
    WordOrder,
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
        raise InvalidRequestError(
            f"{node_name} 当前地址类型不支持按 {config.data_type} 解码"
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
            ">h", _registers_to_bytes(registers=registers, word_order=config.word_order)
        )
    if config.data_type == "uint32":
        return _unpack_scalar(
            ">I", _registers_to_bytes(registers=registers, word_order=config.word_order)
        )
    if config.data_type == "int32":
        return _unpack_scalar(
            ">i", _registers_to_bytes(registers=registers, word_order=config.word_order)
        )
    if config.data_type == "uint64":
        return _unpack_scalar(
            ">Q", _registers_to_bytes(registers=registers, word_order=config.word_order)
        )
    if config.data_type == "int64":
        return _unpack_scalar(
            ">q", _registers_to_bytes(registers=registers, word_order=config.word_order)
        )
    if config.data_type == "float":
        return _unpack_scalar(
            ">f", _registers_to_bytes(registers=registers, word_order=config.word_order)
        )
    if config.data_type == "double":
        return _unpack_scalar(
            ">d", _registers_to_bytes(registers=registers, word_order=config.word_order)
        )
    if config.data_type == "string":
        assert config.string_length is not None
        raw_bytes = _registers_to_bytes(
            registers=registers, word_order=config.word_order
        )
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
    raise InvalidRequestError(
        f"{node_name} 不支持当前 data_type", details={"data_type": config.data_type}
    )


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
        return _bytes_to_registers(
            payload=struct.pack(">h", normalized), word_order=config.word_order
        )
    if data_type == "uint32":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=0,
            maximum=0xFFFFFFFF,
        )
        return _bytes_to_registers(
            payload=struct.pack(">I", normalized), word_order=config.word_order
        )
    if data_type == "int32":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=-(2**31),
            maximum=2**31 - 1,
        )
        return _bytes_to_registers(
            payload=struct.pack(">i", normalized), word_order=config.word_order
        )
    if data_type == "uint64":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=0,
            maximum=0xFFFFFFFFFFFFFFFF,
        )
        return _bytes_to_registers(
            payload=struct.pack(">Q", normalized), word_order=config.word_order
        )
    if data_type == "int64":
        normalized = _coerce_int_value(
            raw_value=raw_value,
            node_name=node_name,
            field_name="value",
            minimum=-(2**63),
            maximum=2**63 - 1,
        )
        return _bytes_to_registers(
            payload=struct.pack(">q", normalized), word_order=config.word_order
        )
    if data_type == "float":
        normalized = _coerce_float_value(
            raw_value=raw_value, node_name=node_name, field_name="value"
        )
        return _bytes_to_registers(
            payload=struct.pack(">f", normalized), word_order=config.word_order
        )
    if data_type == "double":
        normalized = _coerce_float_value(
            raw_value=raw_value, node_name=node_name, field_name="value"
        )
        return _bytes_to_registers(
            payload=struct.pack(">d", normalized), word_order=config.word_order
        )
    if data_type == "string":
        if not isinstance(raw_value, str):
            raise InvalidRequestError(f"{node_name} 的 value 必须是字符串")
        try:
            encoded_bytes = raw_value.encode(config.string_encoding)
        except Exception as exc:
            raise InvalidRequestError(
                f"{node_name} 无法按指定 string_encoding 编码字符串",
                details={
                    "string_encoding": config.string_encoding,
                    "error_message": str(exc),
                },
            ) from exc
        target_length = config.string_length or len(encoded_bytes)
        if target_length <= 0:
            raise InvalidRequestError(f"{node_name} 的 string_length 必须大于 0")
        if len(encoded_bytes) > target_length:
            raise InvalidRequestError(
                f"{node_name} 的字符串长度超过 string_length",
                details={
                    "string_length": target_length,
                    "actual_length": len(encoded_bytes),
                },
            )
        padded_bytes = encoded_bytes.ljust(target_length, b"\x00")
        if len(padded_bytes) % 2 != 0:
            padded_bytes += b"\x00"
        return _bytes_to_registers(payload=padded_bytes, word_order=config.word_order)
    raise InvalidRequestError(
        f"{node_name} 不支持当前 data_type", details={"data_type": data_type}
    )


def _registers_to_bytes(*, registers: list[int], word_order: WordOrder) -> bytes:
    """把寄存器列表按指定 word order 展平成字节序列。"""

    normalized_registers = list(registers)
    if word_order == "little":
        normalized_registers.reverse()
    return b"".join(
        struct.pack(">H", register_value) for register_value in normalized_registers
    )


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
