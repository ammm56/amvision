"""工业结果/报警对象节点共享 helper。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.nodes.video_runtime_support import require_video_payload
from backend.service.application.errors import InvalidRequestError


def require_ok_ng_value(raw_value: object, *, field_name: str = "decision") -> str:
    """校验 OK / NG 决策值。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().upper()
    if normalized_value not in {"OK", "NG"}:
        raise InvalidRequestError(f"{field_name} 仅支持 OK 或 NG")
    return normalized_value


def read_optional_value_input(raw_payload: object, *, field_name: str) -> object | None:
    """读取可选 value.v1 输入。"""

    if raw_payload is None:
        return None
    return require_value_payload(raw_payload, field_name=field_name)["value"]


def read_optional_reason_input(raw_payload: object) -> str | None:
    """读取可选 reason 输入。"""

    if raw_payload is None:
        return None
    reason_value = require_value_payload(raw_payload, field_name="reason")["value"]
    if not isinstance(reason_value, str) or not reason_value.strip():
        raise InvalidRequestError("reason 输入必须是非空字符串")
    return reason_value.strip()


def require_alarm_record_payload(payload: object, *, field_name: str = "alarm") -> dict[str, object]:
    """校验 alarm-record.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(f"{field_name} payload 必须是对象")
    active_value = payload.get("active")
    level_value = payload.get("level")
    message_value = payload.get("message")
    if not isinstance(active_value, bool):
        raise InvalidRequestError(f"{field_name}.active 必须是布尔值")
    if not isinstance(level_value, str) or level_value.strip().lower() not in {"info", "warning", "error", "critical"}:
        raise InvalidRequestError(f"{field_name}.level 仅支持 info/warning/error/critical")
    if not isinstance(message_value, str) or not message_value.strip():
        raise InvalidRequestError(f"{field_name}.message 必须是非空字符串")
    normalized_payload: dict[str, object] = {
        "active": active_value,
        "level": level_value.strip().lower(),
        "message": message_value.strip(),
    }
    code_value = payload.get("code")
    if code_value is not None:
        if not isinstance(code_value, str) or not code_value.strip():
            raise InvalidRequestError(f"{field_name}.code 必须是非空字符串")
        normalized_payload["code"] = code_value.strip()
    if "metrics" in payload:
        normalized_payload["metrics"] = payload.get("metrics")
    metadata_value = payload.get("metadata")
    if metadata_value is not None:
        if not isinstance(metadata_value, dict):
            raise InvalidRequestError(f"{field_name}.metadata 必须是对象")
        normalized_payload["metadata"] = dict(metadata_value)
    image_value = payload.get("image")
    if image_value is not None:
        normalized_payload["image"] = require_image_payload(image_value)
    video_value = payload.get("video")
    if video_value is not None:
        normalized_payload["video"] = require_video_payload(video_value)
    return normalized_payload


def build_result_record_payload(
    *,
    ok_ng: str,
    metrics_value: object | None = None,
    conditions_value: object | None = None,
    reason_value: str | None = None,
    metadata_value: object | None = None,
    alarm_payload: object | None = None,
    image_payload: object | None = None,
    video_payload: object | None = None,
) -> dict[str, object]:
    """组装统一的 result-record.v1 payload。"""

    normalized_ok_ng = require_ok_ng_value(ok_ng, field_name="ok_ng")
    result_payload: dict[str, object] = {
        "ok_ng": normalized_ok_ng,
        "ok": normalized_ok_ng == "OK",
    }
    if reason_value is not None:
        result_payload["reason"] = reason_value
    if metrics_value is not None:
        result_payload["metrics"] = metrics_value
    if conditions_value is not None:
        result_payload["conditions"] = conditions_value
    if metadata_value is not None:
        result_payload["metadata"] = metadata_value
    if alarm_payload is not None:
        result_payload["alarm"] = require_alarm_record_payload(alarm_payload)
    if image_payload is not None:
        result_payload["image"] = require_image_payload(image_payload)
    if video_payload is not None:
        result_payload["video"] = require_video_payload(video_payload)
    return result_payload


__all__ = [
    "build_result_record_payload",
    "read_optional_reason_input",
    "read_optional_value_input",
    "require_alarm_record_payload",
    "require_ok_ng_value",
]
