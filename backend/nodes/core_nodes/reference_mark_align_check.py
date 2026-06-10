"""参考标记对位检查节点。"""

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


NODE_NAME = "reference-mark-align-check"


def _reference_mark_align_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按参考特征与标记特征的相对偏移做对位检查。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    reference_selector = read_region_selector(
        request.parameters.get("reference_selector"),
        node_name=NODE_NAME,
        field_name="reference_selector",
    )
    mark_selector = read_region_selector(
        request.parameters.get("mark_selector"),
        node_name=NODE_NAME,
        field_name="mark_selector",
    )
    expected_dx = read_required_number(request.parameters.get("expected_dx"), field_name="expected_dx")
    expected_dy = read_required_number(request.parameters.get("expected_dy"), field_name="expected_dy")
    max_abs_dx_error = read_optional_non_negative_number(
        request.parameters.get("max_abs_dx_error"),
        field_name="max_abs_dx_error",
    )
    max_abs_dy_error = read_optional_non_negative_number(
        request.parameters.get("max_abs_dy_error"),
        field_name="max_abs_dy_error",
    )
    max_distance_error_pixels = read_optional_non_negative_number(
        request.parameters.get("max_distance_error_pixels"),
        field_name="max_distance_error_pixels",
    )
    if (
        max_abs_dx_error is None
        and max_abs_dy_error is None
        and max_distance_error_pixels is None
    ):
        raise InvalidRequestError(f"{NODE_NAME} 节点至少需要设置一个对位误差阈值")

    reference_candidates = select_region_candidates(regions_payload["items"], selector=reference_selector)
    mark_candidates = select_region_candidates(regions_payload["items"], selector=mark_selector)
    reference_item = select_single_region_item(reference_candidates, strategy=reference_selector["strategy"])
    mark_item = select_single_region_item(mark_candidates, strategy=mark_selector["strategy"])
    if reference_item is None or mark_item is None:
        reason = "missing-reference-region" if reference_item is None else "missing-mark-region"
        return {
            "result": build_boolean_payload(False),
            "metrics": build_value_payload(
                {
                    "reason": reason,
                    "result": False,
                    "reference_selector": build_selector_summary(reference_selector),
                    "mark_selector": build_selector_summary(mark_selector),
                    "reference_candidate_count": len(reference_candidates),
                    "mark_candidate_count": len(mark_candidates),
                    "selected_reference_region_id": None if reference_item is None else reference_item["region_id"],
                    "selected_mark_region_id": None if mark_item is None else mark_item["region_id"],
                }
            ),
        }
    if str(reference_item["region_id"]) == str(mark_item["region_id"]):
        return {
            "result": build_boolean_payload(False),
            "metrics": build_value_payload(
                {
                    "reason": "same-region-selected",
                    "result": False,
                    "reference_selector": build_selector_summary(reference_selector),
                    "mark_selector": build_selector_summary(mark_selector),
                    "reference_candidate_count": len(reference_candidates),
                    "mark_candidate_count": len(mark_candidates),
                    "selected_reference_region_id": reference_item["region_id"],
                    "selected_mark_region_id": mark_item["region_id"],
                }
            ),
        }

    reference_center_x, reference_center_y = compute_bbox_center(reference_item["bbox_xyxy"], node_name=NODE_NAME)
    mark_center_x, mark_center_y = compute_bbox_center(mark_item["bbox_xyxy"], node_name=NODE_NAME)
    actual_dx = float(mark_center_x - reference_center_x)
    actual_dy = float(mark_center_y - reference_center_y)
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
                "reference_selector": build_selector_summary(reference_selector),
                "mark_selector": build_selector_summary(mark_selector),
                "reference_candidate_count": len(reference_candidates),
                "mark_candidate_count": len(mark_candidates),
                "selected_reference_region_id": reference_item["region_id"],
                "selected_reference_class_name": reference_item.get("class_name"),
                "selected_mark_region_id": mark_item["region_id"],
                "selected_mark_class_name": mark_item.get("class_name"),
                "reference_center_x": reference_center_x,
                "reference_center_y": reference_center_y,
                "mark_center_x": mark_center_x,
                "mark_center_y": mark_center_y,
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


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.reference-mark-align-check",
        display_name="Reference Mark Align Check",
        category="vision.assembly",
        description="按参考特征和标记特征选中一对区域，检查标记相对基准的对位偏移是否超差，适合丝印标记、贴标基准点、打标位置和定位孔相对基准到位检查。",
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
                "reference_selector": {
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
                "mark_selector": {
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
                "expected_dx": {"type": "number", "title": "期望 X 偏移"},
                "expected_dy": {"type": "number", "title": "期望 Y 偏移"},
                "max_abs_dx_error": {"type": "number", "minimum": 0, "title": "最大 X 偏移误差"},
                "max_abs_dy_error": {"type": "number", "minimum": 0, "title": "最大 Y 偏移误差"},
                "max_distance_error_pixels": {"type": "number", "minimum": 0, "title": "最大距离误差"},
            },
            "required": ["reference_selector", "mark_selector", "expected_dx", "expected_dy"],
        },
        capability_tags=("vision.assembly", "inspection.alignment", "inspection.reference-mark"),
    ),
    handler=_reference_mark_align_check_handler,
)
