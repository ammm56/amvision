"""批量槽位空/满状态统计节点。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.nodes.image_refs_slot_metrics import (
    read_optional_positive_int,
    read_ratio_with_default,
)


NODE_TYPE_ID = "custom.opencv.slot-batch-state"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """合并空槽检查和有料检查结果，输出整批槽位的空盘/满盘/异常状态。"""

    empty_summary = _require_summary_value(
        request.input_values.get("empty_check"),
        field_name="empty_check",
        expected_format_id="amvision.image-refs-empty-check.v1",
    )
    occupied_summary = _require_summary_value(
        request.input_values.get("occupied_check"),
        field_name="occupied_check",
        expected_format_id="amvision.image-refs-occupied-check.v1",
    )
    expected_count = read_optional_positive_int(request.parameters.get("expected_count"), field_name="expected_count")
    empty_min_empty_ratio = read_ratio_with_default(
        request.parameters.get("empty_min_empty_ratio"),
        field_name="empty_min_empty_ratio",
        default_value=1.0,
    )
    full_min_occupied_ratio = read_ratio_with_default(
        request.parameters.get("full_min_occupied_ratio"),
        field_name="full_min_occupied_ratio",
        default_value=0.94,
    )

    empty_count = _read_non_negative_count(empty_summary, "empty_count", field_name="empty_check.empty_count")
    occupied_count = _read_non_negative_count(
        occupied_summary,
        "occupied_count",
        field_name="occupied_check.occupied_count",
    )
    empty_total = _read_positive_count(empty_summary, "count", field_name="empty_check.count")
    occupied_total = _read_positive_count(occupied_summary, "count", field_name="occupied_check.count")
    total_count = max(empty_total, occupied_total)
    if empty_total != occupied_total:
        count_state = "mismatched"
    elif expected_count is not None and total_count != expected_count:
        count_state = "unexpected"
    else:
        count_state = "ok"

    empty_ratio = empty_count / empty_total
    occupied_ratio = occupied_count / occupied_total
    empty_pass = count_state == "ok" and empty_ratio >= empty_min_empty_ratio
    full_pass = count_state == "ok" and occupied_ratio >= full_min_occupied_ratio
    tray_state = _resolve_tray_state(empty_pass=empty_pass, full_pass=full_pass, count_state=count_state)
    payload = {
        "format_id": "amvision.slot-batch-state.v1",
        "expected_count": expected_count,
        "count": total_count,
        "count_state": count_state,
        "empty_count": empty_count,
        "occupied_count": occupied_count,
        "empty_ratio": round(empty_ratio, 8),
        "occupied_ratio": round(occupied_ratio, 8),
        "empty_min_empty_ratio": empty_min_empty_ratio,
        "full_min_occupied_ratio": full_min_occupied_ratio,
        "is_empty_tray": tray_state == "empty-tray",
        "is_full_tray": tray_state == "full-tray",
        "tray_state": tray_state,
        "state": "ok" if tray_state in {"empty-tray", "full-tray"} else "ng",
        "empty_check_state": empty_summary.get("state"),
        "occupied_check_state": occupied_summary.get("state"),
    }
    return {
        "summary": build_value_payload(payload),
        "body": {
            "type": "slot-batch-state",
            **payload,
        },
    }


def _require_summary_value(payload: object, *, field_name: str, expected_format_id: str) -> dict[str, object]:
    """读取 value.v1 summary 并校验 format_id。"""

    value_payload = require_value_payload(payload, field_name=field_name)
    value = value_payload["value"]
    if not isinstance(value, dict):
        raise InvalidRequestError(f"{field_name} 必须是对象 value")
    format_id = value.get("format_id")
    if not is_empty_parameter(format_id) and format_id != expected_format_id:
        raise InvalidRequestError(f"{field_name} format_id 必须是 {expected_format_id}")
    return dict(value)


def _read_positive_count(summary: dict[str, object], key: str, *, field_name: str) -> int:
    """读取正整数计数。"""

    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    normalized_value = int(value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value


def _read_non_negative_count(summary: dict[str, object], key: str, *, field_name: str) -> int:
    """读取非负整数计数。"""

    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是非负整数")
    normalized_value = int(value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 必须大于等于 0")
    return normalized_value


def _resolve_tray_state(*, empty_pass: bool, full_pass: bool, count_state: str) -> str:
    """合并空盘和满盘规则状态。"""

    if count_state != "ok":
        return "failed"
    if empty_pass and full_pass:
        return "conflicting"
    if empty_pass:
        return "empty-tray"
    if full_pass:
        return "full-tray"
    return "partial-or-abnormal"
