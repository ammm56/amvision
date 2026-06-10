"""零件对相对偏移检查节点。"""

from __future__ import annotations

import math

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._region_node_support import (
    filter_region_items,
    require_regions_payload,
    select_best_region_item,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "pair-offset-check"


def _pair_offset_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按两组目标规则选中一对零件，并检查相对偏移是否贴近期望向量。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    source_selector = _read_selector(request.parameters.get("source_selector"), field_name="source_selector")
    target_selector = _read_selector(request.parameters.get("target_selector"), field_name="target_selector")
    expected_dx = _read_required_number(request.parameters.get("expected_dx"), field_name="expected_dx")
    expected_dy = _read_required_number(request.parameters.get("expected_dy"), field_name="expected_dy")
    max_abs_dx_error = _read_optional_non_negative_number(
        request.parameters.get("max_abs_dx_error"),
        field_name="max_abs_dx_error",
    )
    max_abs_dy_error = _read_optional_non_negative_number(
        request.parameters.get("max_abs_dy_error"),
        field_name="max_abs_dy_error",
    )
    max_distance_error_pixels = _read_optional_non_negative_number(
        request.parameters.get("max_distance_error_pixels"),
        field_name="max_distance_error_pixels",
    )
    if (
        max_abs_dx_error is None
        and max_abs_dy_error is None
        and max_distance_error_pixels is None
    ):
        raise InvalidRequestError(f"{NODE_NAME} 节点至少需要设置一个偏移误差阈值")

    source_candidates = _select_candidate_items(regions_payload["items"], selector=source_selector)
    target_candidates = _select_candidate_items(regions_payload["items"], selector=target_selector)
    source_item = select_best_region_item(source_candidates, strategy=source_selector["strategy"])
    target_item = select_best_region_item(target_candidates, strategy=target_selector["strategy"])
    if source_item is None or target_item is None:
        reason = "missing-source-region" if source_item is None else "missing-target-region"
        return {
            "result": build_boolean_payload(False),
            "metrics": build_value_payload(
                {
                    "reason": reason,
                    "result": False,
                    "source_selector": _build_selector_summary(source_selector),
                    "target_selector": _build_selector_summary(target_selector),
                    "source_candidate_count": len(source_candidates),
                    "target_candidate_count": len(target_candidates),
                    "selected_source_region_id": None if source_item is None else source_item["region_id"],
                    "selected_target_region_id": None if target_item is None else target_item["region_id"],
                }
            ),
        }
    if str(source_item["region_id"]) == str(target_item["region_id"]):
        return {
            "result": build_boolean_payload(False),
            "metrics": build_value_payload(
                {
                    "reason": "same-region-selected",
                    "result": False,
                    "source_selector": _build_selector_summary(source_selector),
                    "target_selector": _build_selector_summary(target_selector),
                    "source_candidate_count": len(source_candidates),
                    "target_candidate_count": len(target_candidates),
                    "selected_source_region_id": source_item["region_id"],
                    "selected_target_region_id": target_item["region_id"],
                }
            ),
        }

    source_center_x, source_center_y = _compute_bbox_center(source_item["bbox_xyxy"])
    target_center_x, target_center_y = _compute_bbox_center(target_item["bbox_xyxy"])
    actual_dx = float(target_center_x - source_center_x)
    actual_dy = float(target_center_y - source_center_y)
    dx_error = float(actual_dx - expected_dx)
    dy_error = float(actual_dy - expected_dy)
    actual_distance_pixels = float(math.hypot(actual_dx, actual_dy))
    expected_distance_pixels = float(math.hypot(expected_dx, expected_dy))
    distance_error_pixels = float(abs(actual_distance_pixels - expected_distance_pixels))
    failure_reasons: list[str] = []
    if max_abs_dx_error is not None and abs(dx_error) > max_abs_dx_error:
        failure_reasons.append("dx-error-too-large")
    if max_abs_dy_error is not None and abs(dy_error) > max_abs_dy_error:
        failure_reasons.append("dy-error-too-large")
    if max_distance_error_pixels is not None and distance_error_pixels > max_distance_error_pixels:
        failure_reasons.append("distance-error-too-large")
    result_value = len(failure_reasons) == 0
    return {
        "result": build_boolean_payload(result_value),
        "metrics": build_value_payload(
            {
                "result": result_value,
                "failure_reasons": failure_reasons,
                "source_selector": _build_selector_summary(source_selector),
                "target_selector": _build_selector_summary(target_selector),
                "source_candidate_count": len(source_candidates),
                "target_candidate_count": len(target_candidates),
                "selected_source_region_id": source_item["region_id"],
                "selected_source_class_name": source_item.get("class_name"),
                "selected_target_region_id": target_item["region_id"],
                "selected_target_class_name": target_item.get("class_name"),
                "source_center_x": source_center_x,
                "source_center_y": source_center_y,
                "target_center_x": target_center_x,
                "target_center_y": target_center_y,
                "actual_dx": actual_dx,
                "actual_dy": actual_dy,
                "expected_dx": expected_dx,
                "expected_dy": expected_dy,
                "dx_error": dx_error,
                "dy_error": dy_error,
                "actual_distance_pixels": actual_distance_pixels,
                "expected_distance_pixels": expected_distance_pixels,
                "distance_error_pixels": distance_error_pixels,
                "max_abs_dx_error": max_abs_dx_error,
                "max_abs_dy_error": max_abs_dy_error,
                "max_distance_error_pixels": max_distance_error_pixels,
            }
        ),
    }


def _select_candidate_items(
    items: list[dict[str, object]],
    *,
    selector: dict[str, object],
) -> list[dict[str, object]]:
    """按 selector 过滤候选区域。"""

    class_id = selector["class_id"]
    class_name = selector["class_name"]
    prompt_id = selector["prompt_id"]
    state = selector["state"]
    return filter_region_items(
        items,
        min_score=selector["min_score"],
        max_score=selector["max_score"],
        min_area=selector["min_area"],
        max_area=selector["max_area"],
        class_ids={class_id} if class_id is not None else None,
        class_names={class_name} if class_name is not None else None,
        prompt_ids={prompt_id} if prompt_id is not None else None,
        track_ids=None,
        states={state} if state is not None else None,
    )


def _read_selector(raw_value: object, *, field_name: str) -> dict[str, object]:
    """读取 source/target selector 参数。"""

    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是对象")
    class_name = _read_optional_text(raw_value.get("class_name"), field_name=f"{field_name}.class_name")
    class_id = _read_optional_non_negative_int(raw_value.get("class_id"), field_name=f"{field_name}.class_id")
    prompt_id = _read_optional_text(raw_value.get("prompt_id"), field_name=f"{field_name}.prompt_id")
    state = _read_optional_text(raw_value.get("state"), field_name=f"{field_name}.state")
    if class_name is None and class_id is None and prompt_id is None and state is None:
        raise InvalidRequestError(
            f"{NODE_NAME} 节点的 {field_name} 至少需要提供 class_name、class_id、prompt_id 或 state 之一"
        )
    return {
        "strategy": _read_strategy(raw_value.get("strategy"), field_name=f"{field_name}.strategy"),
        "class_name": class_name,
        "class_id": class_id,
        "prompt_id": prompt_id,
        "state": state,
        "min_score": _read_optional_non_negative_number(raw_value.get("min_score"), field_name=f"{field_name}.min_score"),
        "max_score": _read_optional_non_negative_number(raw_value.get("max_score"), field_name=f"{field_name}.max_score"),
        "min_area": _read_optional_non_negative_int(raw_value.get("min_area"), field_name=f"{field_name}.min_area"),
        "max_area": _read_optional_non_negative_int(raw_value.get("max_area"), field_name=f"{field_name}.max_area"),
    }


def _read_strategy(raw_value: object, *, field_name: str) -> str:
    """读取单侧零件选择策略。"""

    if raw_value is None:
        return "largest-area"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"largest-area", "highest-score", "first"}:
        raise InvalidRequestError(f"{field_name} 仅支持 largest-area、highest-score 或 first")
    return normalized_value


def _read_required_number(raw_value: object, *, field_name: str) -> float:
    """读取必填数值参数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    return float(raw_value)


def _read_optional_non_negative_number(raw_value: object, *, field_name: str) -> float | None:
    """读取可选非负数值。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    normalized_value = float(raw_value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def _read_optional_non_negative_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选非负整数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(f"{field_name} 必须是非负整数")
    return int(raw_value)


def _read_optional_text(raw_value: object, *, field_name: str) -> str | None:
    """读取可选文本。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _compute_bbox_center(bbox_xyxy: object) -> tuple[float, float]:
    """根据 bbox_xyxy 计算中心点。"""

    if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
        raise InvalidRequestError(f"{NODE_NAME} 需要长度为 4 的 bbox_xyxy")
    x1_value = float(bbox_xyxy[0])
    y1_value = float(bbox_xyxy[1])
    x2_value = float(bbox_xyxy[2])
    y2_value = float(bbox_xyxy[3])
    return (x1_value + x2_value) / 2.0, (y1_value + y2_value) / 2.0


def _build_selector_summary(selector: dict[str, object]) -> dict[str, object]:
    """构造 selector 摘要。"""

    return {
        "strategy": selector["strategy"],
        "class_name": selector["class_name"],
        "class_id": selector["class_id"],
        "prompt_id": selector["prompt_id"],
        "state": selector["state"],
        "min_score": selector["min_score"],
        "max_score": selector["max_score"],
        "min_area": selector["min_area"],
        "max_area": selector["max_area"],
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.pair-offset-check",
        display_name="Pair Offset Check",
        category="vision.assembly",
        description="按 source/target 两组零件规则选中一对区域，检查相对中心偏移是否接近期望装配向量，适合双孔、双销、连接件和左右对称部件到位检查。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "source_selector": {
                    "type": "object",
                    "properties": {
                        "strategy": {"type": "string", "enum": ["largest-area", "highest-score", "first"]},
                        "class_name": {"type": "string"},
                        "class_id": {"type": "integer", "minimum": 0},
                        "prompt_id": {"type": "string"},
                        "state": {"type": "string"},
                        "min_score": {"type": "number", "minimum": 0},
                        "max_score": {"type": "number", "minimum": 0},
                        "min_area": {"type": "integer", "minimum": 0},
                        "max_area": {"type": "integer", "minimum": 0}
                    }
                },
                "target_selector": {
                    "type": "object",
                    "properties": {
                        "strategy": {"type": "string", "enum": ["largest-area", "highest-score", "first"]},
                        "class_name": {"type": "string"},
                        "class_id": {"type": "integer", "minimum": 0},
                        "prompt_id": {"type": "string"},
                        "state": {"type": "string"},
                        "min_score": {"type": "number", "minimum": 0},
                        "max_score": {"type": "number", "minimum": 0},
                        "min_area": {"type": "integer", "minimum": 0},
                        "max_area": {"type": "integer", "minimum": 0}
                    }
                },
                "expected_dx": {"type": "number", "title": "期望 X 偏移"},
                "expected_dy": {"type": "number", "title": "期望 Y 偏移"},
                "max_abs_dx_error": {"type": "number", "minimum": 0, "title": "最大 X 偏移误差"},
                "max_abs_dy_error": {"type": "number", "minimum": 0, "title": "最大 Y 偏移误差"},
                "max_distance_error_pixels": {"type": "number", "minimum": 0, "title": "最大距离误差"},
            },
            "required": ["source_selector", "target_selector", "expected_dx", "expected_dy"],
        },
        capability_tags=("vision.assembly", "inspection.offset", "inspection.pair-offset"),
    ),
    handler=_pair_offset_check_handler,
)
