"""目标间距检查节点。"""

from __future__ import annotations

import math

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._assembly_node_support import (
    REGION_SELECTION_STRATEGY_ENUM,
    build_selector_summary,
    compute_bbox_center,
    read_optional_non_negative_number,
    read_region_selector,
    read_required_number,
    select_region_candidates,
    select_single_region_item,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._region_node_support import require_regions_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "spacing-check"
SPACING_MODE_ENUM = (
    "center-x",
    "center-y",
    "center-distance",
    "edge-gap-x",
    "edge-gap-y",
)


def _spacing_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按两组目标规则选中两个区域，并检查间距是否贴近期望值。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    source_selector = read_region_selector(
        request.parameters.get("source_selector"),
        node_name=NODE_NAME,
        field_name="source_selector",
    )
    target_selector = read_region_selector(
        request.parameters.get("target_selector"),
        node_name=NODE_NAME,
        field_name="target_selector",
    )
    spacing_mode = _read_spacing_mode(request.parameters.get("spacing_mode"))
    expected_spacing = read_required_number(request.parameters.get("expected_spacing"), field_name="expected_spacing")
    max_abs_spacing_error = read_optional_non_negative_number(
        request.parameters.get("max_abs_spacing_error"),
        field_name="max_abs_spacing_error",
    )
    if max_abs_spacing_error is None:
        raise InvalidRequestError(f"{NODE_NAME} 节点需要设置 max_abs_spacing_error")

    source_candidates = select_region_candidates(regions_payload["items"], selector=source_selector)
    target_candidates = select_region_candidates(regions_payload["items"], selector=target_selector)
    source_item = select_single_region_item(source_candidates, strategy=source_selector["strategy"])
    target_item = select_single_region_item(target_candidates, strategy=target_selector["strategy"])
    if source_item is None or target_item is None:
        reason = "missing-source-region" if source_item is None else "missing-target-region"
        return {
            "result": build_boolean_payload(False),
            "metrics": build_value_payload(
                {
                    "reason": reason,
                    "result": False,
                    "spacing_mode": spacing_mode,
                    "source_selector": build_selector_summary(source_selector),
                    "target_selector": build_selector_summary(target_selector),
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
                    "spacing_mode": spacing_mode,
                    "source_selector": build_selector_summary(source_selector),
                    "target_selector": build_selector_summary(target_selector),
                    "source_candidate_count": len(source_candidates),
                    "target_candidate_count": len(target_candidates),
                    "selected_source_region_id": source_item["region_id"],
                    "selected_target_region_id": target_item["region_id"],
                }
            ),
        }

    source_center_x, source_center_y = compute_bbox_center(source_item["bbox_xyxy"], node_name=NODE_NAME)
    target_center_x, target_center_y = compute_bbox_center(target_item["bbox_xyxy"], node_name=NODE_NAME)
    signed_center_dx = float(target_center_x - source_center_x)
    signed_center_dy = float(target_center_y - source_center_y)
    actual_spacing = _compute_spacing_value(
        source_item=source_item,
        target_item=target_item,
        spacing_mode=spacing_mode,
        signed_center_dx=signed_center_dx,
        signed_center_dy=signed_center_dy,
    )
    spacing_error = float(actual_spacing - expected_spacing)
    result_value = abs(spacing_error) <= max_abs_spacing_error
    failure_reasons = [] if result_value else ["spacing-error-too-large"]
    return {
        "result": build_boolean_payload(result_value),
        "metrics": build_value_payload(
            {
                "result": result_value,
                "failure_reasons": failure_reasons,
                "spacing_mode": spacing_mode,
                "source_selector": build_selector_summary(source_selector),
                "target_selector": build_selector_summary(target_selector),
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
                "signed_center_dx": signed_center_dx,
                "signed_center_dy": signed_center_dy,
                "expected_spacing": expected_spacing,
                "actual_spacing": actual_spacing,
                "spacing_error": spacing_error,
                "max_abs_spacing_error": max_abs_spacing_error,
            }
        ),
    }


def _read_spacing_mode(raw_value: object) -> str:
    """读取间距判定模式。"""

    if raw_value is None:
        return "center-distance"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 spacing_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in SPACING_MODE_ENUM:
        raise InvalidRequestError(
            f"{NODE_NAME} 节点的 spacing_mode 仅支持 {', '.join(SPACING_MODE_ENUM)}"
        )
    return normalized_value


def _compute_spacing_value(
    *,
    source_item: dict[str, object],
    target_item: dict[str, object],
    spacing_mode: str,
    signed_center_dx: float,
    signed_center_dy: float,
) -> float:
    """按 spacing_mode 计算实际间距。"""

    if spacing_mode == "center-x":
        return float(abs(signed_center_dx))
    if spacing_mode == "center-y":
        return float(abs(signed_center_dy))
    if spacing_mode == "center-distance":
        return float(math.hypot(signed_center_dx, signed_center_dy))
    source_x1, source_y1, source_x2, source_y2 = _read_bbox_xyxy(source_item["bbox_xyxy"])
    target_x1, target_y1, target_x2, target_y2 = _read_bbox_xyxy(target_item["bbox_xyxy"])
    if spacing_mode == "edge-gap-x":
        return float(target_x1 - source_x2)
    if spacing_mode == "edge-gap-y":
        return float(target_y1 - source_y2)
    raise InvalidRequestError("不支持的 spacing_mode", details={"spacing_mode": spacing_mode})


def _read_bbox_xyxy(raw_value: object) -> tuple[float, float, float, float]:
    """读取 bbox_xyxy。"""

    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise InvalidRequestError(f"{NODE_NAME} 需要长度为 4 的 bbox_xyxy")
    return (
        float(raw_value[0]),
        float(raw_value[1]),
        float(raw_value[2]),
        float(raw_value[3]),
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.spacing-check",
        display_name="Spacing Check",
        category="vision.assembly",
        description="按 source/target 两组目标规则选中两个区域，检查中心距或边间距是否超差，适合孔距、销距、标签间隔、器件排布和相邻工位间距检查。",
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
                "target_selector": {
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
                "spacing_mode": {
                    "type": "string",
                    "enum": list(SPACING_MODE_ENUM),
                    "default": "center-distance",
                    "title": "间距模式",
                },
                "expected_spacing": {"type": "number", "title": "期望间距"},
                "max_abs_spacing_error": {"type": "number", "minimum": 0, "title": "最大间距误差"},
            },
            "required": ["source_selector", "target_selector", "expected_spacing", "max_abs_spacing_error"],
        },
        capability_tags=("vision.assembly", "inspection.spacing", "inspection.layout"),
    ),
    handler=_spacing_check_handler,
)
