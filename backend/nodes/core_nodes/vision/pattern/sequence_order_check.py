"""目标排列顺序检查节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.assembly import (
    REGION_SELECTION_STRATEGY_ENUM,
    build_selector_summary,
    compute_bbox_center,
    read_optional_non_negative_number,
    read_region_selector,
    select_region_candidates,
    select_single_region_item,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes.support.region import require_regions_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "sequence-order-check"
ORDER_MODE_ENUM = (
    "left-to-right",
    "right-to-left",
    "top-to-bottom",
    "bottom-to-top",
)


def _sequence_order_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按指定顺序依次选中目标，并检查它们沿指定方向的排列是否正确。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    order_mode = _read_order_mode(request.parameters.get("order_mode"))
    min_position_delta = read_optional_non_negative_number(
        request.parameters.get("min_position_delta"),
        field_name="min_position_delta",
    )
    if min_position_delta is None:
        min_position_delta = 0.0
    ordered_items = _read_ordered_items(request.parameters.get("ordered_items"))

    selected_items: list[dict[str, object]] = []
    used_region_ids: set[str] = set()
    for ordered_item in ordered_items:
        candidate_items = [
            item
            for item in select_region_candidates(regions_payload["items"], selector=ordered_item["selector"])
            if str(item["region_id"]) not in used_region_ids
        ]
        selected_item = select_single_region_item(candidate_items, strategy=ordered_item["selector"]["strategy"])
        if selected_item is None:
            return {
                "result": build_boolean_payload(False),
                "metrics": build_value_payload(
                    {
                        "reason": "missing-ordered-item",
                        "result": False,
                        "order_mode": order_mode,
                        "min_position_delta": min_position_delta,
                        "missing_item_name": ordered_item["item_name"],
                        "missing_item_index": ordered_item["item_index"],
                        "items": selected_items,
                    }
                ),
            }
        used_region_ids.add(str(selected_item["region_id"]))
        center_x, center_y = compute_bbox_center(selected_item["bbox_xyxy"], node_name=NODE_NAME)
        axis_position = _compute_axis_position(
            order_mode=order_mode,
            center_x=center_x,
            center_y=center_y,
        )
        selected_items.append(
            {
                "item_name": ordered_item["item_name"],
                "item_index": ordered_item["item_index"],
                "selector": build_selector_summary(ordered_item["selector"]),
                "candidate_count": len(candidate_items),
                "region_id": str(selected_item["region_id"]),
                "class_name": selected_item.get("class_name"),
                "class_id": selected_item.get("class_id"),
                "center_x": center_x,
                "center_y": center_y,
                "axis_position": axis_position,
            }
        )

    violation = _find_order_violation(
        order_mode=order_mode,
        min_position_delta=min_position_delta,
        selected_items=selected_items,
    )
    if violation is not None:
        return {
            "result": build_boolean_payload(False),
            "metrics": build_value_payload(
                {
                    "reason": "order-violation",
                    "result": False,
                    "order_mode": order_mode,
                    "min_position_delta": min_position_delta,
                    "items": selected_items,
                    **violation,
                }
            ),
        }
    return {
        "result": build_boolean_payload(True),
        "metrics": build_value_payload(
            {
                "result": True,
                "order_mode": order_mode,
                "min_position_delta": min_position_delta,
                "ordered_item_count": len(selected_items),
                "selected_region_ids": [item["region_id"] for item in selected_items],
                "selected_item_names": [item["item_name"] for item in selected_items],
                "items": selected_items,
            }
        ),
    }


def _read_order_mode(raw_value: object) -> str:
    """读取顺序模式。"""

    if raw_value is None:
        return "left-to-right"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 order_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in ORDER_MODE_ENUM:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 order_mode 仅支持 {', '.join(ORDER_MODE_ENUM)}")
    return normalized_value


def _read_ordered_items(raw_value: object) -> list[dict[str, object]]:
    """读取期望顺序的目标列表。"""

    if not isinstance(raw_value, list) or len(raw_value) < 2:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 ordered_items 必须是至少 2 项的数组")
    normalized_items: list[dict[str, object]] = []
    for item_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, dict):
            raise InvalidRequestError(f"{NODE_NAME} 节点的 ordered_items[{item_index}] 必须是对象")
        item_name = _read_required_text(
            item_value.get("item_name"),
            field_name=f"ordered_items[{item_index}].item_name",
        )
        selector = read_region_selector(
            item_value.get("selector"),
            node_name=NODE_NAME,
            field_name=f"ordered_items[{item_index}].selector",
        )
        normalized_items.append(
            {
                "item_name": item_name,
                "item_index": item_index,
                "selector": selector,
            }
        )
    return normalized_items


def _read_required_text(raw_value: object, *, field_name: str) -> str:
    """读取必填文本。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    return raw_value.strip()


def _compute_axis_position(
    *,
    order_mode: str,
    center_x: float,
    center_y: float,
) -> float:
    """按顺序模式取用于比较的轴位置。"""

    if order_mode in {"left-to-right", "right-to-left"}:
        return float(center_x)
    return float(center_y)


def _find_order_violation(
    *,
    order_mode: str,
    min_position_delta: float,
    selected_items: list[dict[str, object]],
) -> dict[str, object] | None:
    """查找第一处顺序违反项。"""

    for previous_item, current_item in zip(selected_items, selected_items[1:], strict=False):
        previous_position = float(previous_item["axis_position"])
        current_position = float(current_item["axis_position"])
        actual_delta = float(current_position - previous_position)
        if order_mode in {"left-to-right", "top-to-bottom"}:
            if actual_delta <= min_position_delta:
                return {
                    "violation_previous_item_name": previous_item["item_name"],
                    "violation_current_item_name": current_item["item_name"],
                    "violation_previous_region_id": previous_item["region_id"],
                    "violation_current_region_id": current_item["region_id"],
                    "violation_previous_axis_position": previous_position,
                    "violation_current_axis_position": current_position,
                    "violation_actual_delta": actual_delta,
                }
            continue
        if actual_delta >= -min_position_delta:
            return {
                "violation_previous_item_name": previous_item["item_name"],
                "violation_current_item_name": current_item["item_name"],
                "violation_previous_region_id": previous_item["region_id"],
                "violation_current_region_id": current_item["region_id"],
                "violation_previous_axis_position": previous_position,
                "violation_current_axis_position": current_position,
                "violation_actual_delta": actual_delta,
            }
    return None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.sequence-order-check",
        display_name="Sequence Order Check",
        category="vision.assembly",
        description="按期望顺序依次选中多个区域，检查它们沿左右或上下方向的排列是否正确，适合多工位排布、元件装配顺序、标签序列和治具孔位顺序检查。",
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
                "order_mode": {
                    "type": "string",
                    "enum": list(ORDER_MODE_ENUM),
                    "default": "left-to-right",
                    "title": "顺序方向",
                },
                "min_position_delta": {
                    "type": "number",
                    "minimum": 0,
                    "default": 0,
                    "title": "最小位置间隔",
                },
                "ordered_items": {
                    "type": "array",
                    "title": "期望顺序目标列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_name": {"type": "string"},
                            "selector": {
                                "type": "object",
                                "properties": {
                                    "strategy": {"type": "string", "enum": list(REGION_SELECTION_STRATEGY_ENUM)},
                                    "class_name": {"type": "string"},
                                    "class_id": {"type": "integer", "minimum": 0},
                                    "prompt_id": {"type": "string"},
                                    "track_id": {"type": "string"},
                                    "state": {"type": "string"},
                                    "min_score": {"type": "number", "minimum": 0},
                                    "max_score": {"type": "number", "minimum": 0},
                                    "min_area": {"type": "integer", "minimum": 0},
                                    "max_area": {"type": "integer", "minimum": 0},
                                },
                            },
                        },
                        "required": ["item_name", "selector"],
                    },
                    "minItems": 2,
                },
            },
            "required": ["ordered_items"],
        },
        capability_tags=("vision.assembly", "inspection.sequence", "inspection.layout"),
    ),
    handler=_sequence_order_check_handler,
)
