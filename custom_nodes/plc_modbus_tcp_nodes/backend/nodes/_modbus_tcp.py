"""项目内最小 Modbus TCP client 实现。"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Callable, TypeVar


@dataclass(frozen=True)
class ModbusBitsReadResponse:
    """描述一次 bit 读取的响应。"""

    bits: list[bool]
    address: int
    count: int
    dev_id: int
    transaction_id: int
    function_code: int
    retries: int
    exception_code: int = 0


@dataclass(frozen=True)
class ModbusRegistersReadResponse:
    """描述一次寄存器读取的响应。"""

    registers: list[int]
    address: int
    count: int
    dev_id: int
    transaction_id: int
    function_code: int
    retries: int
    exception_code: int = 0


@dataclass(frozen=True)
class ModbusWriteResponse:
    """描述一次写入请求的确认响应。"""

    address: int
    count: int
    dev_id: int
    transaction_id: int
    function_code: int
    retries: int
    acknowledged_values: list[int | bool]
    exception_code: int = 0


class ModbusTcpError(Exception):
    """Modbus TCP 底层异常基类。"""


class ModbusTcpConnectionError(ModbusTcpError):
    """连接建立或链路读写失败。"""


class ModbusTcpTimeoutError(ModbusTcpError):
    """等待设备响应超时。"""


class ModbusTcpProtocolError(ModbusTcpError):
    """设备返回了非法或不一致的报文。"""


class ModbusTcpDeviceError(ModbusTcpError):
    """设备返回 Modbus exception response。"""

    def __init__(
        self,
        message: str,
        *,
        function_code: int,
        exception_code: int,
    ) -> None:
        super().__init__(message)
        self.function_code = function_code
        self.exception_code = exception_code


_T = TypeVar("_T")


class ProjectModbusTcpClient:
    """只覆盖当前 pack 所需功能的同步 Modbus TCP client。"""

    def __init__(
        self,
        host: str,
        *,
        port: int,
        timeout: float,
        retries: int,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._retries = retries
        self._socket: socket.socket | None = None
        self._transaction_id = 0

    def connect(self) -> bool:
        """建立到目标设备的 TCP 连接。"""

        self.close()
        try:
            client_socket = socket.create_connection(
                (self._host, self._port),
                timeout=self._timeout,
            )
            client_socket.settimeout(self._timeout)
        except TimeoutError as exc:
            raise ModbusTcpTimeoutError(str(exc) or "连接超时") from exc
        except OSError as exc:
            raise ModbusTcpConnectionError(str(exc) or "连接失败") from exc
        self._socket = client_socket
        return True

    def close(self) -> None:
        """关闭当前连接。"""

        if self._socket is None:
            return
        try:
            self._socket.close()
        finally:
            self._socket = None

    def read_coils(
        self,
        address: int,
        *,
        count: int,
        device_id: int,
    ) -> ModbusBitsReadResponse:
        """读取 coils。"""

        return self._read_bits(
            function_code=1,
            address=address,
            count=count,
            device_id=device_id,
        )

    def read_discrete_inputs(
        self,
        address: int,
        *,
        count: int,
        device_id: int,
    ) -> ModbusBitsReadResponse:
        """读取 discrete inputs。"""

        return self._read_bits(
            function_code=2,
            address=address,
            count=count,
            device_id=device_id,
        )

    def read_holding_registers(
        self,
        address: int,
        *,
        count: int,
        device_id: int,
    ) -> ModbusRegistersReadResponse:
        """读取 holding registers。"""

        return self._read_registers(
            function_code=3,
            address=address,
            count=count,
            device_id=device_id,
        )

    def read_input_registers(
        self,
        address: int,
        *,
        count: int,
        device_id: int,
    ) -> ModbusRegistersReadResponse:
        """读取 input registers。"""

        return self._read_registers(
            function_code=4,
            address=address,
            count=count,
            device_id=device_id,
        )

    def write_single_coil(
        self,
        address: int,
        value: bool,
        *,
        device_id: int,
    ) -> ModbusWriteResponse:
        """写入单个 coil。"""

        encoded_value = 0xFF00 if value else 0x0000
        payload = struct.pack(">HH", address, encoded_value)
        return self._perform_transaction(
            expected_function_code=5,
            request_payload=payload,
            device_id=device_id,
            response_parser=lambda payload_bytes, retry_count, transaction_id, function_code: ModbusWriteResponse(
                address=struct.unpack(">H", payload_bytes[:2])[0],
                count=1,
                dev_id=device_id,
                transaction_id=transaction_id,
                function_code=function_code,
                retries=retry_count,
                acknowledged_values=[value],
            ),
        )

    def write_single_register(
        self,
        address: int,
        value: int,
        *,
        device_id: int,
    ) -> ModbusWriteResponse:
        """写入单个 holding register。"""

        payload = struct.pack(">HH", address, value)
        return self._perform_transaction(
            expected_function_code=6,
            request_payload=payload,
            device_id=device_id,
            response_parser=lambda payload_bytes, retry_count, transaction_id, function_code: ModbusWriteResponse(
                address=struct.unpack(">H", payload_bytes[:2])[0],
                count=1,
                dev_id=device_id,
                transaction_id=transaction_id,
                function_code=function_code,
                retries=retry_count,
                acknowledged_values=[value],
            ),
        )

    def write_multiple_registers(
        self,
        address: int,
        values: list[int],
        *,
        device_id: int,
    ) -> ModbusWriteResponse:
        """写入多个 holding registers。"""

        register_bytes = b"".join(struct.pack(">H", item) for item in values)
        payload = struct.pack(">HHB", address, len(values), len(register_bytes)) + register_bytes
        return self._perform_transaction(
            expected_function_code=16,
            request_payload=payload,
            device_id=device_id,
            response_parser=lambda payload_bytes, retry_count, transaction_id, function_code: ModbusWriteResponse(
                address=struct.unpack(">H", payload_bytes[:2])[0],
                count=struct.unpack(">H", payload_bytes[2:4])[0],
                dev_id=device_id,
                transaction_id=transaction_id,
                function_code=function_code,
                retries=retry_count,
                acknowledged_values=list(values),
            ),
        )

    def _read_bits(
        self,
        *,
        function_code: int,
        address: int,
        count: int,
        device_id: int,
    ) -> ModbusBitsReadResponse:
        """发送一次 bit 类读取请求。"""

        payload = struct.pack(">HH", address, count)
        return self._perform_transaction(
            expected_function_code=function_code,
            request_payload=payload,
            device_id=device_id,
            response_parser=lambda payload_bytes, retry_count, transaction_id, response_function_code: ModbusBitsReadResponse(
                bits=_decode_modbus_bit_values(payload_bytes=payload_bytes, count=count),
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=transaction_id,
                function_code=response_function_code,
                retries=retry_count,
            ),
        )

    def _read_registers(
        self,
        *,
        function_code: int,
        address: int,
        count: int,
        device_id: int,
    ) -> ModbusRegistersReadResponse:
        """发送一次寄存器读取请求。"""

        payload = struct.pack(">HH", address, count)
        return self._perform_transaction(
            expected_function_code=function_code,
            request_payload=payload,
            device_id=device_id,
            response_parser=lambda payload_bytes, retry_count, transaction_id, response_function_code: ModbusRegistersReadResponse(
                registers=_decode_modbus_register_values(payload_bytes=payload_bytes, count=count),
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=transaction_id,
                function_code=response_function_code,
                retries=retry_count,
            ),
        )

    def _perform_transaction(
        self,
        *,
        expected_function_code: int,
        request_payload: bytes,
        device_id: int,
        response_parser: Callable[[bytes, int, int, int], _T],
    ) -> _T:
        """执行一次带自动重试的 Modbus 事务。"""

        last_error: Exception | None = None
        for attempt_index in range(self._retries + 1):
            try:
                if self._socket is None:
                    self.connect()
                transaction_id = self._next_transaction_id()
                request_frame = self._build_request_frame(
                    transaction_id=transaction_id,
                    device_id=device_id,
                    function_code=expected_function_code,
                    payload=request_payload,
                )
                assert self._socket is not None
                self._socket.sendall(request_frame)
                response_function_code, response_payload = self._receive_response(
                    expected_transaction_id=transaction_id,
                    expected_device_id=device_id,
                )
                if response_function_code & 0x80:
                    original_function_code = response_function_code & 0x7F
                    exception_code = response_payload[0] if response_payload else 0
                    raise ModbusTcpDeviceError(
                        f"设备返回异常响应，function_code={original_function_code}，exception_code={exception_code}",
                        function_code=original_function_code,
                        exception_code=exception_code,
                    )
                if response_function_code != expected_function_code:
                    raise ModbusTcpProtocolError(
                        f"响应 function_code 不匹配，期望 {expected_function_code}，实际 {response_function_code}"
                    )
                return response_parser(
                    response_payload,
                    attempt_index,
                    transaction_id,
                    response_function_code,
                )
            except ModbusTcpDeviceError:
                self.close()
                raise
            except socket.timeout as exc:
                self.close()
                last_error = ModbusTcpTimeoutError(str(exc) or "设备响应超时")
            except TimeoutError as exc:
                self.close()
                last_error = ModbusTcpTimeoutError(str(exc) or "设备响应超时")
            except OSError as exc:
                self.close()
                last_error = ModbusTcpConnectionError(str(exc) or "链路读写失败")
            except ModbusTcpProtocolError as exc:
                self.close()
                last_error = exc
        assert last_error is not None
        raise last_error

    def _build_request_frame(
        self,
        *,
        transaction_id: int,
        device_id: int,
        function_code: int,
        payload: bytes,
    ) -> bytes:
        """把 PDU 封装成完整的 Modbus TCP frame。"""

        pdu = bytes([function_code]) + payload
        mbap = struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, device_id)
        return mbap + pdu

    def _receive_response(
        self,
        *,
        expected_transaction_id: int,
        expected_device_id: int,
    ) -> tuple[int, bytes]:
        """接收并校验一次响应帧。"""

        header = self._read_exactly(7)
        transaction_id, protocol_id, payload_length, device_id = struct.unpack(">HHHB", header)
        if protocol_id != 0:
            raise ModbusTcpProtocolError(f"响应 protocol_id 非法: {protocol_id}")
        if transaction_id != expected_transaction_id:
            raise ModbusTcpProtocolError(
                f"响应 transaction_id 不匹配，期望 {expected_transaction_id}，实际 {transaction_id}"
            )
        if device_id != expected_device_id:
            raise ModbusTcpProtocolError(
                f"响应 unit_id 不匹配，期望 {expected_device_id}，实际 {device_id}"
            )
        if payload_length < 2:
            raise ModbusTcpProtocolError(f"响应长度非法: {payload_length}")
        pdu = self._read_exactly(payload_length - 1)
        function_code = pdu[0]
        return function_code, pdu[1:]

    def _read_exactly(self, size: int) -> bytes:
        """从 socket 中读取指定长度字节。"""

        assert self._socket is not None
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise ModbusTcpConnectionError("设备提前关闭连接")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _next_transaction_id(self) -> int:
        """生成下一个 transaction id。"""

        self._transaction_id = (self._transaction_id % 0xFFFF) + 1
        return self._transaction_id


def _decode_modbus_bit_values(*, payload_bytes: bytes, count: int) -> list[bool]:
    """解析 bit 读取响应。"""

    if not payload_bytes:
        raise ModbusTcpProtocolError("bit 读取响应缺少 byte_count")
    byte_count = payload_bytes[0]
    packed_bytes = payload_bytes[1:]
    if byte_count != len(packed_bytes):
        raise ModbusTcpProtocolError(
            f"bit 读取响应 byte_count 不匹配，声明 {byte_count}，实际 {len(packed_bytes)}"
        )
    bits: list[bool] = []
    for payload_byte in packed_bytes:
        for bit_index in range(8):
            bits.append(bool((payload_byte >> bit_index) & 0x01))
            if len(bits) >= count:
                return bits
    if len(bits) != count:
        raise ModbusTcpProtocolError(f"bit 读取响应长度不足，期望 {count}，实际 {len(bits)}")
    return bits


def _decode_modbus_register_values(*, payload_bytes: bytes, count: int) -> list[int]:
    """解析寄存器读取响应。"""

    if not payload_bytes:
        raise ModbusTcpProtocolError("寄存器读取响应缺少 byte_count")
    byte_count = payload_bytes[0]
    register_bytes = payload_bytes[1:]
    expected_byte_count = count * 2
    if byte_count != len(register_bytes):
        raise ModbusTcpProtocolError(
            f"寄存器读取响应 byte_count 不匹配，声明 {byte_count}，实际 {len(register_bytes)}"
        )
    if byte_count != expected_byte_count:
        raise ModbusTcpProtocolError(
            f"寄存器读取响应长度不匹配，期望 {expected_byte_count}，实际 {byte_count}"
        )
    return list(struct.unpack(f">{count}H", register_bytes))
