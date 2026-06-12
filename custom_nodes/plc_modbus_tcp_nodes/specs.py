"""PLC Modbus TCP 节点包规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "plc.modbus-tcp-nodes"
NODE_PACK_VERSION = "0.1.0"

READ_VALUE_NODE_TYPE_ID = "custom.plc.modbus.read-value"
WRITE_VALUE_NODE_TYPE_ID = "custom.plc.modbus.write-value"
WAIT_CONDITION_NODE_TYPE_ID = "custom.plc.modbus.wait-condition"
WRITE_RESULT_SIGNALS_NODE_TYPE_ID = "custom.plc.modbus.write-result-signals"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (
    READ_VALUE_NODE_TYPE_ID,
    WRITE_VALUE_NODE_TYPE_ID,
    WAIT_CONDITION_NODE_TYPE_ID,
    WRITE_RESULT_SIGNALS_NODE_TYPE_ID,
)
