"""三态码与布尔放行位分开，不连接真实 PLC。"""

from types import SimpleNamespace

import pytest

from backend.nodes.core_nodes.support.inspection_record import (
    build_result_record_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.infrastructure.integrations.modbus import ModbusWriteResponse
from custom_nodes.plc_nodes.protocols.modbus_tcp.backend.nodes import (
    write_result_signals,
)
from custom_nodes.plc_nodes.protocols.modbus_tcp.backend.runtime import (
    client as client_module,
)


def request(state, mapping=None, overrides=None):
    """使用独立显式测试码，不作为现场默认寄存器配置。"""
    values = {
        "result": build_result_record_payload(
            state=state, reason_value="missing" if state == "invalid" else None
        )
    }
    if overrides:
        values["request"] = {"value": overrides}
    return WorkflowNodeExecutionRequest(
        node_id="signals",
        node_definition=SimpleNamespace(node_type_id=write_result_signals.NODE_TYPE_ID),
        parameters={
            "host": "127.0.0.1",
            "signal_mappings": [
                {
                    "signal_name": "decision",
                    "source_scope": "result",
                    "source_path": "state",
                    "data_type": "uint16",
                    "register_address": "400001",
                    "state_values": {"ok": 7, "ng": 8, "invalid": 9},
                    **(mapping or {}),
                }
            ],
        },
        input_values=values,
        execution_metadata={},
    )


@pytest.mark.parametrize("state,expected", [("ok", 7), ("ng", 8), ("invalid", 9)])
def test_explicit_three_codes_reach_existing_writer(monkeypatch, state, expected):
    """三种结果保留不同码且客户端正常关闭，不把 INVALID 合并成 NG。"""
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            return True

        def close(self):
            calls.append("closed")

        def write_single_register(self, address, value, *, device_id):
            calls.append((address, value))
            return ModbusWriteResponse(
                address=address,
                count=1,
                dev_id=device_id,
                transaction_id=1,
                function_code=6,
                retries=0,
                acknowledged_values=[value],
            )

    monkeypatch.setattr(client_module, "ProjectModbusTcpClient", Client)
    output = write_result_signals.handle_node(request(state))
    assert calls == [(0, expected), "closed"]
    assert output["result"]["value"]["failed_count"] == 0


@pytest.mark.parametrize(
    "mapping,overrides",
    [
        ({"state_values": {"ok": 1, "ng": 2}}, None),
        ({"state_values": {"ok": 1, "ng": 2, "invalid": 2}}, None),
        ({"state_values": {"ok": True, "ng": 2, "invalid": 3}}, None),
        ({"state_values": {"ok": 1, "ng": 2, "invalid": 65536}}, None),
        ({"true_value": 1, "false_value": 2}, None),
        ({"data_type": "bool", "register_address": "00001"}, None),
        ({"state_values": None}, None),
        ({}, {"signal_values": {"decision": 7}}),
        (
            {"data_type": "string", "string_length": 8, "state_values": None},
            {"signal_values": {"decision": "ok"}},
        ),
    ],
)
def test_bad_codes_or_request_override_fail_before_connection(
    monkeypatch, mapping, overrides
):
    """坏映射不能在早期信号已写出后才报错，也不能覆盖 INVALID 为 OK。"""

    def no_client(*args, **kwargs):
        pytest.fail("invalid mapping must not connect")

    monkeypatch.setattr(client_module, "ProjectModbusTcpClient", no_client)
    with pytest.raises(InvalidRequestError):
        write_result_signals.handle_node(request("invalid", mapping, overrides))


@pytest.mark.parametrize("value", [None, 65536, -1, "bad"])
@pytest.mark.parametrize("continue_on_error", [False, True])
def test_later_bad_measurement_is_rejected_before_any_signal_write(
    monkeypatch, value, continue_on_error
):
    """后面的量值无法编码时，不得先写出前面的状态或放行码。"""

    def no_client(*args, **kwargs):
        pytest.fail("all payload encoding must precede connection")

    monkeypatch.setattr(client_module, "ProjectModbusTcpClient", no_client)
    invocation = request("invalid")
    invocation.parameters["continue_on_error"] = continue_on_error
    invocation.parameters["signal_mappings"].append(
        {
            "signal_name": "measurement",
            "source_scope": "result",
            "source_path": "metrics.height",
            "data_type": "uint16",
            "register_address": "400002",
        }
    )
    invocation.input_values["result"]["metrics"] = {"height": value}
    with pytest.raises(InvalidRequestError):
        write_result_signals.handle_node(invocation)
