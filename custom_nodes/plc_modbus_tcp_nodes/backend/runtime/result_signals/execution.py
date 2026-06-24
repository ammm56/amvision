"""PLC Modbus TCP 结果信号回写执行。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import ServiceError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.client import _open_modbus_client
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _read_request_overrides,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.read_write import (
    _perform_write_operation,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.result_signals.config import (
    build_write_result_signals_config,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.result_signals.payloads import (
    read_effective_alarm_payload,
    require_result_record_payload,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.result_signals.sources import (
    resolve_signal_value,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import ModbusWriteConfig


def execute_write_result_signals_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行 result-record 到 Modbus 点位的信号回写。"""

    request_overrides = _read_request_overrides(request, node_name=node_name)
    config = build_write_result_signals_config(
        request=request,
        node_name=node_name,
        overrides=request_overrides,
    )
    result_payload = require_result_record_payload(
        request.input_values.get("result"),
        field_name="result",
        node_name=node_name,
    )
    alarm_payload = read_effective_alarm_payload(
        explicit_alarm_payload=request.input_values.get("alarm"),
        result_payload=result_payload,
        node_name=node_name,
    )
    written_items: list[dict[str, object]] = []
    skipped_items: list[dict[str, object]] = []
    failed_items: list[dict[str, object]] = []

    with _open_modbus_client(config.connection, node_name=node_name) as client:
        for mapping in config.mappings:
            resolved_value = resolve_signal_value(
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
