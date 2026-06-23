"""批次结果摘要节点共享 helper。"""

from __future__ import annotations

import json
from collections.abc import Sequence

from backend.nodes.core_nodes.support.inspection_record import (
    require_alarm_record_payload,
    require_ok_ng_value,
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
    unknown_count = 0
    alarm_count = 0
    reason_counts: dict[str, int] = {}
    for result_index, result_item in enumerate(inspection_results, start=1):
        ok_ng_value = result_item.get("ok_ng")
        if ok_ng_value is None:
            unknown_count += 1
        else:
            normalized_ok_ng = require_ok_ng_value(
                ok_ng_value,
                field_name=f"inspection_results[{result_index}].ok_ng",
            )
            if normalized_ok_ng == "OK":
                ok_count += 1
            else:
                ng_count += 1
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
        "count": result_count,
        "ok_count": ok_count,
        "ng_count": ng_count,
        "unknown_count": unknown_count,
        "alarm_count": alarm_count,
        "empty": result_count == 0,
        "has_ng": ng_count > 0,
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


__all__ = [
    "build_batch_result_summary",
    "clone_inline_json_value",
    "read_result_item_list_from_multi_payload",
    "read_result_item_list_from_raw_value",
    "read_result_item_list_from_value_payload",
]
