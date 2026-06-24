"""PLC Modbus TCP 等待条件执行。"""

from __future__ import annotations

import time

from backend.nodes.core_nodes.support.logic import build_value_payload, compare_values
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.client import _open_modbus_client
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.config import _build_read_config
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.parameters import (
    _normalize_json_value,
    _read_optional_positive_float_parameter,
    _read_positive_int_parameter,
    _read_request_overrides,
    _read_wait_operator,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.read_write import (
    _perform_read_operation,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    ModbusWaitConditionConfig,
    WaitOperator,
)


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
    expected_value = overrides.get(
        "expected_value", request.parameters.get("expected_value")
    )
    if operator in {
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
            raise InvalidRequestError(
                f"{node_name} 的 contains 只支持字符串 observed_value"
            )
        if not isinstance(expected_value, str):
            raise InvalidRequestError(
                f"{node_name} 的 contains 要求 expected_value 也是字符串"
            )
        return expected_value in observed_value
    if operator in {"bitmask_any_set", "bitmask_all_set"}:
        assert expected_value is not None
        if isinstance(observed_value, bool) or not isinstance(observed_value, int):
            raise InvalidRequestError(
                f"{node_name} 的 {operator} 要求 observed_value 必须是整数"
            )
        if isinstance(expected_value, bool) or not isinstance(expected_value, int):
            raise InvalidRequestError(
                f"{node_name} 的 {operator} 要求 expected_value 必须是整数"
            )
        if operator == "bitmask_any_set":
            return (observed_value & expected_value) != 0
        return (observed_value & expected_value) == expected_value
    raise InvalidRequestError(
        f"{node_name} 不支持当前 wait operator", details={"operator": operator}
    )
