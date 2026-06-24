"""PLC Modbus TCP 结果信号回写输入 payload 校验。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.inspection_record import (
    require_alarm_record_payload,
    require_ok_ng_value,
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
    ok_ng = require_ok_ng_value(
        raw_payload.get("ok_ng"), field_name=f"{field_name}.ok_ng"
    )
    ok_value = raw_payload.get("ok")
    if not isinstance(ok_value, bool):
        raise InvalidRequestError(f"{node_name} 的 {field_name}.ok 必须是布尔值")
    if ok_value != (ok_ng == "OK"):
        raise InvalidRequestError(
            f"{node_name} 的 {field_name}.ok 与 {field_name}.ok_ng 不一致"
        )

    normalized_payload = dict(raw_payload)
    normalized_payload["ok_ng"] = ok_ng
    normalized_payload["ok"] = ok_value
    alarm_value = raw_payload.get("alarm")
    if alarm_value is not None:
        normalized_payload["alarm"] = require_alarm_record_payload(
            alarm_value,
            field_name=f"{field_name}.alarm",
        )
    return normalized_payload


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
