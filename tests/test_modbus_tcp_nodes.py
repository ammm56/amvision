"""PLC Modbus TCP 节点行为测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.service.application.errors import OperationTimeoutError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.integrations.modbus import (
    ModbusBitsReadResponse,
    ModbusRegistersReadResponse,
    ModbusWriteResponse,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.nodes import (
    read_value,
    wait_condition,
    write_value,
)
import custom_nodes.plc_modbus_tcp_nodes.backend.nodes._runtime as modbus_runtime


def test_read_value_node_returns_typed_scalar(monkeypatch) -> None:
    """验证 read-value 会按 data_type 输出标量值。"""

    captured: dict[str, object] = {}

    class _FakeModbusTcpClient:
        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
            captured["client_init"] = {
                "host": host,
                "port": port,
                "timeout": timeout,
                "retries": retries,
            }

        def connect(self) -> bool:
            captured["connect_called"] = True
            return True

        def close(self) -> None:
            captured["close_called"] = True

        def read_holding_registers(
            self,
            address: int,
            *,
            count: int,
            device_id: int,
        ) -> ModbusRegistersReadResponse:
            captured["read_call"] = {
                "address": address,
                "count": count,
                "device_id": device_id,
            }
            return ModbusRegistersReadResponse(
                registers=[125],
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=7,
                function_code=3,
                retries=0,
            )

    monkeypatch.setattr(modbus_runtime, "ProjectModbusTcpClient", _FakeModbusTcpClient)

    output = read_value.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="read-node",
            node_definition=SimpleNamespace(node_type_id=read_value.NODE_TYPE_ID),
            parameters={
                "host": "192.168.10.12",
                "port": 502,
                "unit_id": 3,
                "timeout_seconds": 1.5,
                "retries": 2,
                "register_address": "400001",
                "data_type": "uint16",
            },
            input_values={},
        )
    )

    assert captured["client_init"] == {
        "host": "192.168.10.12",
        "port": 502,
        "timeout": 1.5,
        "retries": 2,
    }
    assert captured["read_call"] == {"address": 0, "count": 1, "device_id": 3}
    assert output["result"]["value"]["transport"] == "modbus-tcp"
    assert output["result"]["value"]["operation"] == "read_value"
    assert output["result"]["value"]["address_family"] == "holding_register"
    assert output["result"]["value"]["zero_based_address"] == 0
    assert output["result"]["value"]["observed_value"] == 125
    assert output["result"]["value"]["response_meta"]["function_code"] == 3


def test_read_value_node_decodes_int64(monkeypatch) -> None:
    """验证 read-value 支持 int64 解码。"""

    class _FakeModbusTcpClient:
        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.retries = retries

        def connect(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def read_holding_registers(
            self,
            address: int,
            *,
            count: int,
            device_id: int,
        ) -> ModbusRegistersReadResponse:
            assert address == 1
            assert count == 4
            assert device_id == 2
            return ModbusRegistersReadResponse(
                registers=[0xFFFF, 0xFFFF, 0xFFFF, 0xFFFE],
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=19,
                function_code=3,
                retries=0,
            )

    monkeypatch.setattr(modbus_runtime, "ProjectModbusTcpClient", _FakeModbusTcpClient)

    output = read_value.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="read-int64-node",
            node_definition=SimpleNamespace(node_type_id=read_value.NODE_TYPE_ID),
            parameters={
                "host": "192.168.10.22",
                "unit_id": 2,
                "register_address": "400002",
                "data_type": "int64",
            },
            input_values={},
        )
    )

    assert output["result"]["value"]["observed_value"] == -2
    assert output["result"]["value"]["raw_values"] == [65535, 65535, 65535, 65534]


def test_write_value_node_supports_request_override(monkeypatch) -> None:
    """验证 write-value 支持 request 输入覆盖参数。"""

    captured: dict[str, object] = {}

    class _FakeModbusTcpClient:
        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
            captured["client_init"] = {
                "host": host,
                "port": port,
                "timeout": timeout,
                "retries": retries,
            }

        def connect(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def write_multiple_registers(
            self,
            address: int,
            values: list[int],
            *,
            device_id: int,
        ) -> ModbusWriteResponse:
            captured["write_call"] = {
                "address": address,
                "values": values,
                "device_id": device_id,
            }
            return ModbusWriteResponse(
                address=address,
                count=len(values),
                dev_id=device_id,
                transaction_id=11,
                function_code=16,
                retries=0,
                acknowledged_values=list(values),
            )

    monkeypatch.setattr(modbus_runtime, "ProjectModbusTcpClient", _FakeModbusTcpClient)

    output = write_value.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="write-node",
            node_definition=SimpleNamespace(node_type_id=write_value.NODE_TYPE_ID),
            parameters={
                "host": "10.0.0.1",
                "register_address": "400010",
                "data_type": "uint32",
                "value": 1,
            },
            input_values={
                "request": {
                    "value": {
                        "host": "10.0.0.25",
                        "port": 1502,
                        "unit_id": 7,
                        "register_address": "400002",
                        "data_type": "uint32",
                        "value": 305419896
                    }
                }
            },
        )
    )

    assert captured["client_init"] == {
        "host": "10.0.0.25",
        "port": 1502,
        "timeout": 3.0,
        "retries": 1,
    }
    assert captured["write_call"] == {
        "address": 1,
        "values": [4660, 22136],
        "device_id": 7,
    }
    assert output["result"]["value"]["operation"] == "write_value"
    assert output["result"]["value"]["encoded_registers"] == [4660, 22136]
    assert output["result"]["value"]["requested_value"] == 305419896
    assert output["result"]["value"]["request_source"] == "request-input"


def test_write_value_node_encodes_uint64(monkeypatch) -> None:
    """验证 write-value 支持 uint64 编码。"""

    captured: dict[str, object] = {}

    class _FakeModbusTcpClient:
        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
            captured["client_init"] = {
                "host": host,
                "port": port,
                "timeout": timeout,
                "retries": retries,
            }

        def connect(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def write_multiple_registers(
            self,
            address: int,
            values: list[int],
            *,
            device_id: int,
        ) -> ModbusWriteResponse:
            captured["write_call"] = {
                "address": address,
                "values": values,
                "device_id": device_id,
            }
            return ModbusWriteResponse(
                address=address,
                count=len(values),
                dev_id=device_id,
                transaction_id=23,
                function_code=16,
                retries=0,
                acknowledged_values=list(values),
            )

    monkeypatch.setattr(modbus_runtime, "ProjectModbusTcpClient", _FakeModbusTcpClient)

    output = write_value.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="write-uint64-node",
            node_definition=SimpleNamespace(node_type_id=write_value.NODE_TYPE_ID),
            parameters={
                "host": "10.0.0.25",
                "unit_id": 7,
                "register_address": "400002",
                "data_type": "uint64",
                "value": 1311768467463790320,
            },
            input_values={},
        )
    )

    assert captured["write_call"] == {
        "address": 1,
        "values": [0x1234, 0x5678, 0x9ABC, 0xDEF0],
        "device_id": 7,
    }
    assert output["result"]["value"]["encoded_registers"] == [0x1234, 0x5678, 0x9ABC, 0xDEF0]
    assert output["result"]["value"]["requested_value"] == 1311768467463790320


def test_wait_condition_node_requires_stable_match_count(monkeypatch) -> None:
    """验证 wait-condition 会按 stable_match_count 连续命中后才放行。"""

    bit_sequence = iter([False, True, True])
    captured_attempts: list[dict[str, object]] = []

    class _FakeModbusTcpClient:
        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.retries = retries

        def connect(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def read_coils(
            self,
            address: int,
            *,
            count: int,
            device_id: int,
        ) -> ModbusBitsReadResponse:
            bit_value = next(bit_sequence)
            captured_attempts.append(
                {
                    "address": address,
                    "count": count,
                    "device_id": device_id,
                    "bit_value": bit_value,
                }
            )
            return ModbusBitsReadResponse(
                bits=[bit_value],
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=17,
                function_code=1,
                retries=0,
            )

    monkeypatch.setattr(modbus_runtime, "ProjectModbusTcpClient", _FakeModbusTcpClient)

    output = wait_condition.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="wait-node",
            node_definition=SimpleNamespace(node_type_id=wait_condition.NODE_TYPE_ID),
            parameters={
                "host": "192.168.0.20",
                "register_address": "00005",
                "data_type": "bool",
                "operator": "eq",
                "expected_value": True,
                "stable_match_count": 2,
                "poll_interval_ms": 1,
                "wait_timeout_seconds": 2.0,
            },
            input_values={},
        )
    )

    assert [item["bit_value"] for item in captured_attempts] == [False, True, True]
    assert output["result"]["value"]["matched"] is True
    assert output["result"]["value"]["attempts"] == 3
    assert output["result"]["value"]["stable_match_count"] == 2
    assert output["result"]["value"]["wait_timeout_seconds"] == 2.0
    assert output["result"]["value"]["last_observed"]["observed_value"] is True


def test_wait_condition_node_defaults_wait_timeout_to_sixty_seconds(monkeypatch) -> None:
    """验证 wait-condition 未显式传 wait_timeout_seconds 时默认使用 60 秒。"""

    class _FakeModbusTcpClient:
        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.retries = retries

        def connect(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def read_coils(
            self,
            address: int,
            *,
            count: int,
            device_id: int,
        ) -> ModbusBitsReadResponse:
            return ModbusBitsReadResponse(
                bits=[False],
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=29,
                function_code=1,
                retries=0,
            )

    perf_counter_values = iter([0.0, 61.0])

    monkeypatch.setattr(modbus_runtime, "ProjectModbusTcpClient", _FakeModbusTcpClient)
    monkeypatch.setattr(modbus_runtime.time, "perf_counter", lambda: next(perf_counter_values))
    monkeypatch.setattr(modbus_runtime.time, "sleep", lambda _: None)

    with pytest.raises(OperationTimeoutError) as exc_info:
        wait_condition.handle_node(
            WorkflowNodeExecutionRequest(
                node_id="wait-default-timeout-node",
                node_definition=SimpleNamespace(node_type_id=wait_condition.NODE_TYPE_ID),
                parameters={
                    "host": "192.168.0.21",
                    "register_address": "00005",
                    "data_type": "bool",
                    "operator": "eq",
                    "expected_value": True,
                    "poll_interval_ms": 1,
                },
                input_values={},
            )
        )

    assert exc_info.value.details["timeout_seconds"] == 60.0


def test_wait_condition_node_supports_null_timeout_for_infinite_wait(monkeypatch) -> None:
    """验证 wait-condition 传 null 时不会套用默认超时。"""

    bit_sequence = iter([False, True])

    class _FakeModbusTcpClient:
        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.retries = retries

        def connect(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def read_coils(
            self,
            address: int,
            *,
            count: int,
            device_id: int,
        ) -> ModbusBitsReadResponse:
            return ModbusBitsReadResponse(
                bits=[next(bit_sequence)],
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=31,
                function_code=1,
                retries=0,
            )

    perf_counter_values = iter([0.0, 61.0, 122.0])

    monkeypatch.setattr(modbus_runtime, "ProjectModbusTcpClient", _FakeModbusTcpClient)
    monkeypatch.setattr(modbus_runtime.time, "perf_counter", lambda: next(perf_counter_values))
    monkeypatch.setattr(modbus_runtime.time, "sleep", lambda _: None)

    output = wait_condition.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="wait-null-timeout-node",
            node_definition=SimpleNamespace(node_type_id=wait_condition.NODE_TYPE_ID),
            parameters={
                "host": "192.168.0.22",
                "register_address": "00005",
                "data_type": "bool",
                "operator": "eq",
                "expected_value": True,
                "poll_interval_ms": 1,
                "wait_timeout_seconds": None,
            },
            input_values={},
        )
    )

    assert output["result"]["value"]["matched"] is True
    assert output["result"]["value"]["attempts"] == 2
    assert output["result"]["value"]["wait_timeout_seconds"] is None
