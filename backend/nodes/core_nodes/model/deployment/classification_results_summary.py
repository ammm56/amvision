"""槽位 classification 结果汇总节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.collection import require_list_value
from backend.nodes.core_nodes.support.logic import build_boolean_payload, build_value_payload, try_extract_value_by_path
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "classification-results-summary"
FORMAT_ID = "amvision.slot-classification-summary.v1"
DEFAULT_EMPTY_LABELS = ("slotempty",)
DEFAULT_FULL_LABELS = ("slotfull",)
DEFAULT_ABNORMAL_LABELS = ("slotabnormal",)
DEFAULT_LABEL_PATHS = (
    "top_item.class_name",
    "top_item.label",
    "top_item.name",
    "items.0.class_name",
    "items.0.label",
    "items.0.name",
)
DEFAULT_SCORE_PATHS = (
    "top_item.score",
    "top_item.confidence",
    "top_item.probability",
    "items.0.score",
    "items.0.confidence",
    "items.0.probability",
)
DEFAULT_CLASS_ID_PATHS = (
    "top_item.class_id",
    "top_item.id",
    "items.0.class_id",
    "items.0.id",
)
DEFAULT_ITEM_META_PATHS = {
    "crop_index": "source_image.crop_index",
    "roi_id": "source_image.roi_id",
    "roi_kind": "source_image.roi_kind",
    "bbox_xyxy": "source_image.bbox_xyxy",
    "image_width": "image_width",
    "image_height": "image_height",
    "latency_ms": "latency_ms",
}
SUPPORTED_TARGET_STATES = {"empty", "full", "none"}


def _classification_results_summary_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """汇总逐槽 classification 结果，并收敛为整盘状态。"""

    result_items = require_list_value(
        request.input_values.get("results"),
        field_name="results",
        node_id=request.node_id,
    )
    expected_count = _read_optional_positive_int(request.parameters.get("expected_count"))
    target_state = _read_target_state(request.parameters.get("target_state"))
    min_score = _read_optional_float(request.parameters.get("min_score"), default=0.0)
    empty_labels = _read_label_set(request.parameters.get("empty_labels"), default=DEFAULT_EMPTY_LABELS)
    full_labels = _read_label_set(request.parameters.get("full_labels"), default=DEFAULT_FULL_LABELS)
    abnormal_labels = _read_label_set(request.parameters.get("abnormal_labels"), default=DEFAULT_ABNORMAL_LABELS)
    include_items = _read_bool(request.parameters.get("include_items"), default=False, parameter_name="include_items")
    include_raw_categories = _read_bool(
        request.parameters.get("include_raw_categories"),
        default=False,
        parameter_name="include_raw_categories",
    )

    normalized_items: list[dict[str, object]] = []
    problem_items: list[dict[str, object]] = []
    empty_count = 0
    full_count = 0
    abnormal_count = 0
    unknown_count = 0
    low_score_count = 0
    for item_index, raw_item in enumerate(result_items, start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError(
                f"{NODE_NAME} 节点要求 results 数组项必须是对象",
                details={"node_id": request.node_id, "item_index": item_index},
            )
        item = _summarize_classification_item(
            item_index=item_index,
            raw_item=raw_item,
            min_score=min_score,
            empty_labels=empty_labels,
            full_labels=full_labels,
            abnormal_labels=abnormal_labels,
            include_raw_categories=include_raw_categories,
        )
        slot_state = item["slot_state"]
        if slot_state == "empty":
            empty_count += 1
        elif slot_state == "full":
            full_count += 1
        elif slot_state == "abnormal":
            abnormal_count += 1
        else:
            unknown_count += 1
        if item["score_passed"] is False:
            low_score_count += 1
        normalized_items.append(item)
        if _is_problem_item(item=item, target_state=target_state):
            problem_items.append(item)

    total_count = len(result_items)
    expected_count_matched = expected_count is None or expected_count == total_count
    all_empty = total_count > 0 and empty_count == total_count and full_count == 0 and abnormal_count == 0 and unknown_count == 0
    all_full = total_count > 0 and full_count == total_count and empty_count == 0 and abnormal_count == 0 and unknown_count == 0
    has_abnormal = abnormal_count > 0
    tray_state = _decide_tray_state(
        total_count=total_count,
        empty_count=empty_count,
        full_count=full_count,
        abnormal_count=abnormal_count,
        unknown_count=unknown_count,
    )
    passed = _decide_passed(
        expected_count_matched=expected_count_matched,
        target_state=target_state,
        all_empty=all_empty,
        all_full=all_full,
        has_abnormal=has_abnormal,
        unknown_count=unknown_count,
    )
    summary: dict[str, object] = {
        "format_id": FORMAT_ID,
        "count": total_count,
        "expected_count": expected_count,
        "expected_count_matched": expected_count_matched,
        "target_state": target_state,
        "tray_state": tray_state,
        "state": "ok" if passed else "ng",
        "passed": passed,
        "empty_count": empty_count,
        "full_count": full_count,
        "abnormal_count": abnormal_count,
        "unknown_count": unknown_count,
        "low_score_count": low_score_count,
        "all_empty": all_empty,
        "all_full": all_full,
        "has_abnormal": has_abnormal,
        "problem_count": len(problem_items),
        "problem_items": problem_items,
        "rules": {
            "empty_labels": sorted(empty_labels),
            "full_labels": sorted(full_labels),
            "abnormal_labels": sorted(abnormal_labels),
            "min_score": min_score,
            "include_items": include_items,
            "include_raw_categories": include_raw_categories,
        },
    }
    if include_items:
        summary["items"] = normalized_items
    return {
        "summary": build_value_payload(summary),
        "passed": build_boolean_payload(passed),
        "all_empty": build_boolean_payload(all_empty),
        "all_full": build_boolean_payload(all_full),
        "has_abnormal": build_boolean_payload(has_abnormal),
    }


def _summarize_classification_item(
    *,
    item_index: int,
    raw_item: dict[str, object],
    min_score: float,
    empty_labels: set[str],
    full_labels: set[str],
    abnormal_labels: set[str],
    include_raw_categories: bool,
) -> dict[str, object]:
    """把单个分类结果压缩为适合整盘判断的槽位状态。"""

    label = _extract_first_text(raw_item, paths=DEFAULT_LABEL_PATHS)
    normalized_label = _normalize_label(label)
    score = _extract_first_number(raw_item, paths=DEFAULT_SCORE_PATHS)
    class_id = _extract_first_number(raw_item, paths=DEFAULT_CLASS_ID_PATHS)
    score_passed = score is None or score >= min_score
    slot_state = "unknown"
    if score_passed and normalized_label in empty_labels:
        slot_state = "empty"
    elif score_passed and normalized_label in full_labels:
        slot_state = "full"
    elif score_passed and normalized_label in abnormal_labels:
        slot_state = "abnormal"
    item: dict[str, object] = {
        "index": item_index,
        "label": label,
        "normalized_label": normalized_label,
        "class_id": int(class_id) if class_id is not None and class_id.is_integer() else class_id,
        "score": score,
        "score_passed": score_passed,
        "slot_state": slot_state,
        "is_empty": slot_state == "empty",
        "is_full": slot_state == "full",
        "is_abnormal": slot_state == "abnormal",
        "is_unknown": slot_state == "unknown",
    }
    for field_name, path in DEFAULT_ITEM_META_PATHS.items():
        exists, value = try_extract_value_by_path(root=raw_item, path=path)
        if exists:
            item[field_name] = value
    if include_raw_categories:
        item["categories"] = dict(raw_item)
    return item


def _decide_tray_state(
    *,
    total_count: int,
    empty_count: int,
    full_count: int,
    abnormal_count: int,
    unknown_count: int,
) -> str:
    """根据各槽位状态决定整盘状态。"""

    if total_count <= 0:
        return "empty-list"
    if unknown_count > 0:
        return "unknown"
    if abnormal_count > 0:
        return "abnormal"
    if empty_count == total_count:
        return "empty"
    if full_count == total_count:
        return "full"
    return "mixed"


def _decide_passed(
    *,
    expected_count_matched: bool,
    target_state: str,
    all_empty: bool,
    all_full: bool,
    has_abnormal: bool,
    unknown_count: int,
) -> bool:
    """根据目标状态决定整盘是否通过。"""

    if not expected_count_matched or has_abnormal or unknown_count > 0:
        return False
    if target_state == "empty":
        return all_empty
    if target_state == "full":
        return all_full
    return True


def _is_problem_item(*, item: dict[str, object], target_state: str) -> bool:
    """判断当前槽位是否需要进入问题列表。"""

    slot_state = item.get("slot_state")
    if item.get("score_passed") is False or slot_state in {"unknown", "abnormal"}:
        return True
    if target_state == "empty":
        return slot_state != "empty"
    if target_state == "full":
        return slot_state != "full"
    return False


def _read_optional_positive_int(raw_value: object) -> int | None:
    """读取可选正整数参数。"""

    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 expected_count 必须是正整数")
    return raw_value


def _read_optional_float(raw_value: object, *, default: float) -> float:
    """读取可选浮点参数。"""

    if raw_value in (None, ""):
        return default
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 min_score 必须是数字")
    value = float(raw_value)
    if value < 0 or value > 1:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 min_score 必须在 0 到 1 之间")
    return value


def _read_bool(raw_value: object, *, default: bool, parameter_name: str) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError(f"{NODE_NAME} 节点的 {parameter_name} 必须是 boolean")


def _read_target_state(raw_value: object) -> str:
    """读取目标整盘状态。"""

    if raw_value in (None, ""):
        return "empty"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 target_state 必须是字符串")
    normalized_value = raw_value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized_value not in SUPPORTED_TARGET_STATES:
        raise InvalidRequestError(
            f"{NODE_NAME} 节点的 target_state 只支持 empty、full、none",
            details={"target_state": raw_value},
        )
    return normalized_value


def _read_label_set(raw_value: object, *, default: tuple[str, ...]) -> set[str]:
    """读取标签集合，并统一转成小写匹配 key。"""

    if raw_value in (None, ""):
        return {_normalize_label(item) for item in default}
    if isinstance(raw_value, str):
        values = [item.strip() for item in raw_value.split(",")]
    elif isinstance(raw_value, list):
        values = raw_value
    else:
        raise InvalidRequestError(f"{NODE_NAME} 节点的标签参数必须是字符串或字符串数组")
    normalized_values = {_normalize_label(item) for item in values if isinstance(item, str) and item.strip()}
    if not normalized_values:
        raise InvalidRequestError(f"{NODE_NAME} 节点的标签参数不能为空")
    return normalized_values


def _extract_first_text(root: dict[str, object], *, paths: tuple[str, ...]) -> str | None:
    """按候选路径提取第一个字符串值。"""

    for path in paths:
        exists, value = try_extract_value_by_path(root=root, path=path)
        if exists and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_first_number(root: dict[str, object], *, paths: tuple[str, ...]) -> float | None:
    """按候选路径提取第一个数字值。"""

    for path in paths:
        exists, value = try_extract_value_by_path(root=root, path=path)
        if exists and not isinstance(value, bool) and isinstance(value, (int, float)):
            return float(value)
    return None


def _normalize_label(label: object) -> str:
    """把分类标签转成稳定匹配 key。"""

    if not isinstance(label, str):
        return ""
    return label.strip().lower().replace("-", "_").replace(" ", "_")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.model.classification-results-summary",
        display_name="Slot Classification Summary",
        category="model.postprocess",
        description="汇总 for-each 逐槽 classification 结果，按 slotempty、slotfull、slotabnormal 判断整盘状态。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="results",
                display_name="Results",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="passed",
                display_name="Passed",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="all_empty",
                display_name="All Empty",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="all_full",
                display_name="All Full",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="has_abnormal",
                display_name="Has Abnormal",
                payload_type_id="boolean.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "expected_count": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 36,
                    "title": "Expected Count",
                    "description": "期望槽位数量；为空时不校验数量。",
                },
                "target_state": {
                    "type": "string",
                    "enum": ["empty", "full", "none"],
                    "default": "empty",
                    "title": "Target State",
                    "description": "整盘目标状态。空盘检测使用 empty，满盘检测使用 full，只统计不判定使用 none。",
                },
                "empty_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": list(DEFAULT_EMPTY_LABELS),
                    "title": "Empty Labels",
                    "description": "模型输出为空槽的标签，默认 slotempty。",
                },
                "full_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": list(DEFAULT_FULL_LABELS),
                    "title": "Full Labels",
                    "description": "模型输出为有料且放置正确的标签，默认 slotfull。",
                },
                "abnormal_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": list(DEFAULT_ABNORMAL_LABELS),
                    "title": "Abnormal Labels",
                    "description": "模型输出为槽位异常的标签，默认 slotabnormal。",
                },
                "min_score": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0,
                    "title": "Min Score",
                    "description": "低于该置信度时归为 unknown。",
                },
                "include_items": {
                    "type": "boolean",
                    "default": False,
                    "title": "Include Items",
                    "description": "是否在 summary 中返回所有槽位明细；生产默认关闭，只返回问题槽位。",
                },
                "include_raw_categories": {
                    "type": "boolean",
                    "default": False,
                    "title": "Include Raw Categories",
                    "description": "是否在每个槽位明细中保留原始 classification 输出；只建议调试时打开。",
                },
            },
        },
        capability_tags=("model.postprocess", "classification", "slot.inspect", "logic.aggregate"),
    ),
    handler=_classification_results_summary_handler,
)
