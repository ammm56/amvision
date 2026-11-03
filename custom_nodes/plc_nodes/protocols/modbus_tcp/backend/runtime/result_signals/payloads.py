"""PLC Modbus TCP 结果信号回写输入 payload 校验。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.inspection_record import (
    require_alarm_record_payload,
    require_result_record_payload as validate_result_record,
)
from backend.service.application.errors import InvalidRequestError


def require_result_record_payload(
    raw_payload: object,
    *,
    field_name: str,
    node_name: str,
) -> dict[str, object]:
    """校验并规范化 result-record 输入。"""

    if not isinstance(raw_payload, dict):
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 输入必须是 result-record 对象"
        )
    return validate_result_record(raw_payload, field_name=f"{node_name}.{field_name}")


def read_effective_alarm_payload(
    *,
    explicit_alarm_payload: object,
    result_payload: dict[str, object],
    node_name: str,
) -> dict[str, object] | None:
    """读取信号回写实际使用的 alarm-record。"""

    if explicit_alarm_payload is not None:
        return require_alarm_record_payload(explicit_alarm_payload, field_name="alarm")
    result_alarm_payload = result_payload.get("alarm")
    if result_alarm_payload is None:
        return None
    return require_alarm_record_payload(result_alarm_payload, field_name="result.alarm")
