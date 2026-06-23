"""regions 偏移检查节点。"""

from __future__ import annotations

import math

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes.support.region import require_regions_payload, select_best_region_item
from backend.nodes.core_nodes.support.roi import (
    read_optional_number,
    require_roi_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "regions-offset-check"


def _regions_offset_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据 ROI 中心和目标中心偏移做超限判断。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    roi_payload = require_roi_payload(request.input_values.get("roi"), node_id=request.node_id)
    strategy = _read_strategy(request.parameters.get("strategy"))
    max_abs_dx = read_optional_number(request.parameters.get("max_abs_dx"), field_name="max_abs_dx", node_name=NODE_NAME)
    max_abs_dy = read_optional_number(request.parameters.get("max_abs_dy"), field_name="max_abs_dy", node_name=NODE_NAME)
    max_distance_pixels = read_optional_number(
        request.parameters.get("max_distance_pixels"),
        field_name="max_distance_pixels",
        node_name=NODE_NAME,
    )
    max_distance_ratio = read_optional_number(
        request.parameters.get("max_distance_ratio"),
        field_name="max_distance_ratio",
        node_name=NODE_NAME,
    )
    if (
        max_abs_dx is None
        and max_abs_dy is None
        and max_distance_pixels is None
        and max_distance_ratio is None
    ):
        raise InvalidRequestError("regions-offset-check 至少要求提供一个偏移阈值")
    selected_item = select_best_region_item(regions_payload["items"], strategy=strategy)
    if selected_item is None:
        return {
            "result": build_boolean_payload(False),
            "metrics": build_value_payload(
                {
                    "strategy": strategy,
                    "selected_region_id": None,
                    "result": False,
                    "reason": "no-region",
                }
            ),
        }
    roi_center_x, roi_center_y = _compute_bbox_center(roi_payload["bbox_xyxy"])
    region_center_x, region_center_y = _compute_bbox_center(selected_item["bbox_xyxy"])
    dx_value = float(region_center_x - roi_center_x)
    dy_value = float(region_center_y - roi_center_y)
    distance_pixels = float(math.sqrt(dx_value * dx_value + dy_value * dy_value))
    roi_width = max(0.0, float(roi_payload["bbox_xyxy"][2]) - float(roi_payload["bbox_xyxy"][0]))
    roi_height = max(0.0, float(roi_payload["bbox_xyxy"][3]) - float(roi_payload["bbox_xyxy"][1]))
    roi_diagonal = float(math.sqrt(roi_width * roi_width + roi_height * roi_height))
    distance_ratio = float(distance_pixels / roi_diagonal) if roi_diagonal > 0 else 0.0
    is_ok = True
    if max_abs_dx is not None and abs(dx_value) > max_abs_dx:
        is_ok = False
    if max_abs_dy is not None and abs(dy_value) > max_abs_dy:
        is_ok = False
    if max_distance_pixels is not None and distance_pixels > max_distance_pixels:
        is_ok = False
    if max_distance_ratio is not None and distance_ratio > max_distance_ratio:
        is_ok = False
    return {
        "result": build_boolean_payload(is_ok),
        "metrics": build_value_payload(
            {
                "strategy": strategy,
                "selected_region_id": selected_item["region_id"],
                "selected_class_name": selected_item.get("class_name"),
                "selected_prompt_id": selected_item.get("prompt_id"),
                "dx": dx_value,
                "dy": dy_value,
                "distance_pixels": distance_pixels,
                "distance_ratio": distance_ratio,
                "roi_center_x": roi_center_x,
                "roi_center_y": roi_center_y,
                "region_center_x": region_center_x,
                "region_center_y": region_center_y,
                "max_abs_dx": max_abs_dx,
                "max_abs_dy": max_abs_dy,
                "max_distance_pixels": max_distance_pixels,
                "max_distance_ratio": max_distance_ratio,
                "result": is_ok,
            }
        ),
    }


def _read_strategy(raw_value: object) -> str:
    """读取目标区域选择策略。"""

    if raw_value is None:
        return "largest-area"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("regions-offset-check 节点的 strategy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"largest-area", "highest-score", "first"}:
        raise InvalidRequestError("regions-offset-check 仅支持 largest-area、highest-score 或 first")
    return normalized_value


def _compute_bbox_center(bbox_xyxy: object) -> tuple[float, float]:
    """根据 bbox_xyxy 计算中心点。"""

    if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
        raise InvalidRequestError("regions-offset-check 需要长度为 4 的 bbox_xyxy")
    x1_value = float(bbox_xyxy[0])
    y1_value = float(bbox_xyxy[1])
    x2_value = float(bbox_xyxy[2])
    y2_value = float(bbox_xyxy[3])
    return (x1_value + x2_value) / 2.0, (y1_value + y2_value) / 2.0


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.regions-offset-check",
        display_name="Regions Offset Check",
        category="vision.roi",
        description="根据目标中心与 ROI 中心的偏移判断是否超限，适合工件落位和贴合偏差规则。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
            NodePortDefinition(
                name="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
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
                "strategy": {
                    "type": "string",
                    "enum": ["largest-area", "highest-score", "first"],
                    "default": "largest-area",
                    "title": "目标选择策略",
                },
                "max_abs_dx": {"type": "number", "title": "X 方向最大偏移"},
                "max_abs_dy": {"type": "number", "title": "Y 方向最大偏移"},
                "max_distance_pixels": {"type": "number", "title": "最大距离像素"},
                "max_distance_ratio": {"type": "number", "title": "最大距离比例"},
            },
        },
        capability_tags=("vision.roi", "inspection.position", "inspection.offset"),
    ),
    handler=_regions_offset_check_handler,
)
