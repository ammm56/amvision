"""classification 逐图结果汇总节点。"""

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
DEFAULT_POSITIVE_LABELS = (
    "empty",
    "empty_slot",
    "slot_empty",
    "no_part",
    "empty-tray-slot",
    "空槽",
    "空",
)
DEFAULT_NEGATIVE_LABELS = (
    "occupied",
    "occupied_slot",
    "slot_occupied",
    "full",
    "filled",
    "part",
    "ng",
    "有料",
    "满槽",
    "满",
)
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


def _classification_results_summary_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """汇总 for-each 逐图 classification 结果。"""

    result_items = require_list_value(
        request.input_values.get("results"),
        field_name="results",
        node_id=request.node_id,
    )
    expected_count = _read_optional_positive_int(request.parameters.get("expected_count"))
    min_score = _read_optional_float(request.parameters.get("min_score"), default=0.0)
    positive_labels = _read_label_set(request.parameters.get("positive_labels"), default=DEFAULT_POSITIVE_LABELS)
    negative_labels = _read_label_set(request.parameters.get("negative_labels"), default=DEFAULT_NEGATIVE_LABELS)
    label_paths = _read_paths(request.parameters.get("label_paths"), default=DEFAULT_LABEL_PATHS)
    score_paths = _read_paths(request.parameters.get("score_paths"), default=DEFAULT_SCORE_PATHS)
    require_known_label = _read_bool(request.parameters.get("require_known_label"), default=False)

    normalized_items: list[dict[str, object]] = []
    positive_count = 0
    negative_count = 0
    unknown_count = 0
    low_score_count = 0
    for item_index, raw_item in enumerate(result_items, start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError(
                f"{NODE_NAME} 节点要求 results 数组项必须是对象",
                details={"node_id": request.node_id, "item_index": item_index},
            )
        label = _extract_first_text(raw_item, paths=label_paths)
        score = _extract_first_number(raw_item, paths=score_paths)
        normalized_label = _normalize_label(label)
        score_passed = score is None or score >= min_score
        decision = "unknown"
        if score_passed and normalized_label in positive_labels:
            decision = "positive"
            positive_count += 1
        elif score_passed and normalized_label in negative_labels:
            decision = "negative"
            negative_count += 1
        else:
            unknown_count += 1
            if score is not None and score < min_score:
                low_score_count += 1

        normalized_items.append(
            {
                "index": item_index,
                "label": label,
                "normalized_label": normalized_label,
                "score": score,
                "score_passed": score_passed,
                "decision": decision,
                "is_positive": decision == "positive",
                "is_negative": decision == "negative",
                "is_unknown": decision == "unknown",
                "categories": dict(raw_item),
            }
        )

    expected_count_matched = expected_count is None or expected_count == len(result_items)
    all_positive = bool(result_items) and positive_count == len(result_items) and unknown_count == 0 and negative_count == 0
    if require_known_label and unknown_count > 0:
        state = "unknown"
    elif all_positive and expected_count_matched:
        state = "ok"
    else:
        state = "ng"
    summary = {
        "format_id": "amvision.classification-results-summary.v1",
        "count": len(result_items),
        "expected_count": expected_count,
        "expected_count_matched": expected_count_matched,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "unknown_count": unknown_count,
        "low_score_count": low_score_count,
        "all_positive": all_positive,
        "any_negative": negative_count > 0,
        "state": state,
        "rules": {
            "positive_labels": sorted(positive_labels),
            "negative_labels": sorted(negative_labels),
            "min_score": min_score,
            "require_known_label": require_known_label,
            "label_paths": list(label_paths),
            "score_paths": list(score_paths),
        },
        "items": normalized_items,
    }
    return {
        "summary": build_value_payload(summary),
        "all_positive": build_boolean_payload(all_positive),
    }


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


def _read_bool(raw_value: object, *, default: bool) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError(f"{NODE_NAME} 节点的 require_known_label 必须是 boolean")


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


def _read_paths(raw_value: object, *, default: tuple[str, ...]) -> tuple[str, ...]:
    """读取候选路径列表。"""

    if raw_value in (None, ""):
        return default
    if isinstance(raw_value, str):
        paths = [item.strip() for item in raw_value.split(",")]
    elif isinstance(raw_value, list):
        paths = [item.strip() for item in raw_value if isinstance(item, str)]
    else:
        raise InvalidRequestError(f"{NODE_NAME} 节点的路径参数必须是字符串或字符串数组")
    normalized_paths = tuple(path for path in paths if path)
    if not normalized_paths:
        raise InvalidRequestError(f"{NODE_NAME} 节点的路径参数不能为空")
    return normalized_paths


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
        display_name="Classification Results Summary",
        category="model.postprocess",
        description="汇总 for-each 逐图 classification 结果，按可配置标签判断正类/负类/未知项，适合逐槽分类后收敛为整盘判断。",
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
                name="all_positive",
                display_name="All Positive",
                payload_type_id="boolean.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "expected_count": {
                    "type": "integer",
                    "minimum": 1,
                    "title": "Expected Count",
                    "description": "期望分类结果数量；为空时不校验数量。",
                },
                "positive_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": list(DEFAULT_POSITIVE_LABELS),
                    "title": "Positive Labels",
                    "description": "判为目标状态的分类标签，例如空槽模型中的 empty。",
                },
                "negative_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": list(DEFAULT_NEGATIVE_LABELS),
                    "title": "Negative Labels",
                    "description": "判为反向状态的分类标签，例如 occupied 或 full。",
                },
                "min_score": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0,
                    "title": "Min Score",
                    "description": "低于该置信度时归为 unknown。",
                },
                "require_known_label": {
                    "type": "boolean",
                    "default": False,
                    "title": "Require Known Label",
                    "description": "为 true 时只要存在 unknown，整体 state 就返回 unknown。",
                },
                "label_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": list(DEFAULT_LABEL_PATHS),
                    "title": "Label Paths",
                },
                "score_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": list(DEFAULT_SCORE_PATHS),
                    "title": "Score Paths",
                },
            },
        },
        capability_tags=("model.postprocess", "classification", "logic.aggregate"),
    ),
    handler=_classification_results_summary_handler,
)
