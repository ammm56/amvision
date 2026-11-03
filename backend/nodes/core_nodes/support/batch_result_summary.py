"""批次结果摘要节点共享 helper。"""

from __future__ import annotations

import json
from collections.abc import Sequence

from backend.nodes.core_nodes.support.inspection_record import (
    require_alarm_record_payload,
    require_result_record_payload,
)
from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.errors import InvalidRequestError


def clone_inline_json_value(raw_value: object) -> object:
    """深拷贝 inline-json 值，避免后续节点直接修改上游对象。"""

    return json.loads(json.dumps(raw_value, ensure_ascii=False))


def read_result_item_list_from_value_payload(
    input_payload: object,
    *,
    node_name: str,
    field_name: str,
) -> list[dict[str, object]]:
    """从 value.v1 输入读取 result-record 对象列表。"""

    if input_payload is None:
        return []
    raw_value = require_value_payload(input_payload, field_name=field_name)["value"]
    return read_result_item_list_from_raw_value(
        raw_value,
        node_name=node_name,
        field_name=f"{field_name}.value",
    )


def read_result_item_list_from_multi_payload(
    raw_payload: object,
    *,
    node_name: str,
    field_name: str,
) -> list[dict[str, object]]:
    """从多值 result-record 输入读取对象列表。"""

    if raw_payload is None:
        return []
    if not isinstance(raw_payload, tuple):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 输入必须是多值端口集合")
    result_items: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_payload, start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError(
                f"{node_name} 的 {field_name} 数组项必须是对象",
                details={"item_index": item_index},
            )
        result_items.append(clone_inline_json_value(raw_item))
    return result_items


def read_result_item_list_from_raw_value(
    raw_value: object,
    *,
    node_name: str,
    field_name: str,
) -> list[dict[str, object]]:
    """从原始对象或对象数组读取 result-record 列表。"""

    if isinstance(raw_value, dict):
        return [clone_inline_json_value(raw_value)]
    if isinstance(raw_value, list):
        result_items: list[dict[str, object]] = []
        for item_index, raw_item in enumerate(raw_value, start=1):
            if not isinstance(raw_item, dict):
                raise InvalidRequestError(
                    f"{node_name} 的 {field_name} 数组项必须是对象",
                    details={"item_index": item_index},
                )
            result_items.append(clone_inline_json_value(raw_item))
        return result_items
    raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是对象或对象数组")


def build_batch_result_summary(
    inspection_results: Sequence[dict[str, object]],
) -> dict[str, object]:
    """把一批 result-record 收成批次摘要。"""

    result_count = len(inspection_results)
    ok_count = 0
    ng_count = 0
    invalid_count = 0
    unknown_count = 0
    alarm_count = 0
    reason_counts: dict[str, int] = {}
    for result_index, result_item in enumerate(inspection_results, start=1):
        try:
            validated = require_result_record_payload(
                result_item, field_name=f"inspection_results[{result_index}]"
            )
        except InvalidRequestError:
            unknown_count += 1
        else:
            if validated["state"] == "ok":
                ok_count += 1
            elif validated["state"] == "ng":
                ng_count += 1
            else:
                invalid_count += 1
        alarm_value = result_item.get("alarm")
        if (
            isinstance(alarm_value, dict)
            and require_alarm_record_payload(
                alarm_value,
                field_name=f"inspection_results[{result_index}].alarm",
            ).get("active")
            is True
        ):
            alarm_count += 1
        reason_value = result_item.get("reason")
        if isinstance(reason_value, str) and reason_value.strip():
            normalized_reason = reason_value.strip()
            reason_counts[normalized_reason] = int(
                reason_counts.get(normalized_reason, 0)
            ) + 1

    summary: dict[str, object] = {
        "format_id": "amvision.inspection-batch-summary.v1",
        "count": result_count,
        "ok_count": ok_count,
        "ng_count": ng_count,
        "invalid_count": invalid_count,
        "unknown_count": unknown_count,
        "alarm_count": alarm_count,
        "empty": result_count == 0,
        "has_ng": ng_count > 0,
        "has_invalid": invalid_count > 0,
        "has_alarm": alarm_count > 0,
        "has_unknown": unknown_count > 0,
        "all_ok": result_count > 0 and ok_count == result_count,
    }
    if result_count > 0:
        summary["pass_ratio"] = ok_count / result_count
    if reason_counts:
        summary["reason_counts"] = reason_counts
        summary["batch_reason_summary"] = [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                reason_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
    return summary


def require_batch_result_summary(raw_value: object) -> dict[str, object]:
    """重读预计算摘要时检查三态分母，不将缺少 INVALID 的旧摘要静默补零。"""
    if not isinstance(raw_value, dict) or raw_value.get("format_id") != "amvision.inspection-batch-summary.v1":
        raise InvalidRequestError("批次摘要格式无效，需要重新生成")
    keys = ("count", "ok_count", "ng_count", "invalid_count", "unknown_count", "alarm_count")
    if any(type(raw_value.get(key)) is not int or raw_value[key] < 0 for key in keys):
        raise InvalidRequestError("批次摘要计数不完整或无效")
    count, ok, ng, invalid, unknown, alarm = (raw_value[key] for key in keys)
    if ok + ng + invalid + unknown != count or alarm > count:
        raise InvalidRequestError("批次摘要计数不一致")
    flags = dict(empty=count == 0, has_ng=ng > 0, has_invalid=invalid > 0,
                 has_unknown=unknown > 0, has_alarm=alarm > 0,
                 all_ok=count > 0 and ok == count)
    if any(raw_value.get(key) is not value for key, value in flags.items()):
        raise InvalidRequestError("批次摘要状态与计数不一致")
    if count:
        ratio = raw_value.get("pass_ratio")
        if type(ratio) not in (int, float) or ratio != ok / count:
            raise InvalidRequestError("批次通过率分母必须包含全部结果")
    elif "pass_ratio" in raw_value:
        raise InvalidRequestError("空批次没有通过率")
    return clone_inline_json_value(raw_value)


__all__ = [
    "build_batch_result_summary",
    "clone_inline_json_value",
    "read_result_item_list_from_multi_payload",
    "read_result_item_list_from_raw_value",
    "read_result_item_list_from_value_payload",
    "require_batch_result_summary",
]
