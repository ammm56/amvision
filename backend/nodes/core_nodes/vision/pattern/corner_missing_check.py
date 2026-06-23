"""缺角检查节点。"""

from __future__ import annotations

import numpy as np

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.assembly import (
    REGION_SELECTION_STRATEGY_ENUM,
    build_selector_summary,
    read_region_selector,
    select_region_candidates,
    select_single_region_item,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes.support.region import (
    build_region_binary_mask,
    require_regions_payload,
    resolve_region_canvas_size,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "corner-missing-check"


def _corner_missing_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """检查单个区域指定角点是否存在明显缺失。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    selector = read_region_selector(
        request.parameters.get("selector"),
        node_name=NODE_NAME,
        field_name="selector",
    )
    corner_name = _read_corner_name(request.parameters.get("corner"))
    window_ratio = _read_window_ratio(request.parameters.get("window_ratio"))
    min_corner_fill_ratio = _read_min_corner_fill_ratio(request.parameters.get("min_corner_fill_ratio"))
    window_shape = _read_window_shape(request.parameters.get("window_shape"))

    candidate_items = select_region_candidates(regions_payload["items"], selector=selector)
    selected_item = select_single_region_item(candidate_items, strategy=selector["strategy"])
    if selected_item is None:
        return {
            "result": build_boolean_payload(False),
            "metrics": build_value_payload(
                {
                    "reason": "missing-target-region",
                    "result": False,
                    "selector": build_selector_summary(selector),
                    "candidate_count": len(candidate_items),
                    "selected_region_id": None,
                    "corner": corner_name,
                    "window_ratio": window_ratio,
                    "window_shape": window_shape,
                    "min_corner_fill_ratio": min_corner_fill_ratio,
                }
            ),
        }

    image_width, image_height = resolve_region_canvas_size(request, regions_payload=regions_payload)
    region_mask = build_region_binary_mask(
        request,
        region_item=selected_item,
        image_width=image_width,
        image_height=image_height,
    )
    corner_mask, window_bbox_xyxy = _build_corner_window_mask(
        bbox_xyxy=selected_item["bbox_xyxy"],
        image_width=image_width,
        image_height=image_height,
        corner_name=corner_name,
        window_ratio=window_ratio,
        window_shape=window_shape,
    )
    corner_area = int(np.count_nonzero(corner_mask))
    occupied_corner_area = int(np.count_nonzero(np.logical_and(region_mask > 0, corner_mask > 0)))
    corner_fill_ratio = float(occupied_corner_area / corner_area) if corner_area > 0 else 0.0
    failure_reasons: list[str] = []
    if corner_fill_ratio < min_corner_fill_ratio:
        failure_reasons.append("low-corner-fill-ratio")
    result_value = len(failure_reasons) == 0
    return {
        "result": build_boolean_payload(result_value),
        "metrics": build_value_payload(
            {
                "result": result_value,
                "failure_reasons": failure_reasons,
                "selector": build_selector_summary(selector),
                "candidate_count": len(candidate_items),
                "selected_region_id": selected_item["region_id"],
                "selected_class_name": selected_item.get("class_name"),
                "corner": corner_name,
                "window_ratio": window_ratio,
                "window_shape": window_shape,
                "window_bbox_xyxy": window_bbox_xyxy,
                "corner_area": corner_area,
                "occupied_corner_area": occupied_corner_area,
                "corner_fill_ratio": round(corner_fill_ratio, 6),
                "min_corner_fill_ratio": min_corner_fill_ratio,
            }
        ),
    }


def _build_corner_window_mask(
    *,
    bbox_xyxy: object,
    image_width: int,
    image_height: int,
    corner_name: str,
    window_ratio: float,
    window_shape: str,
) -> tuple[np.ndarray, list[int]]:
    """构建指定角点的局部检查窗口 mask。"""

    if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
        raise InvalidRequestError(f"{NODE_NAME} 节点要求目标 region 提供长度为 4 的 bbox_xyxy")
    x1_value = int(np.floor(float(bbox_xyxy[0])))
    y1_value = int(np.floor(float(bbox_xyxy[1])))
    x2_value = int(np.ceil(float(bbox_xyxy[2])))
    y2_value = int(np.ceil(float(bbox_xyxy[3])))
    x1_index = max(0, min(image_width, x1_value))
    y1_index = max(0, min(image_height, y1_value))
    x2_index = max(0, min(image_width, x2_value))
    y2_index = max(0, min(image_height, y2_value))
    bbox_width = max(1, x2_index - x1_index)
    bbox_height = max(1, y2_index - y1_index)
    window_width = max(1, int(round(bbox_width * window_ratio)))
    window_height = max(1, int(round(bbox_height * window_ratio)))

    if corner_name == "top-left":
        window_x1, window_y1 = x1_index, y1_index
    elif corner_name == "top-right":
        window_x1, window_y1 = max(x1_index, x2_index - window_width), y1_index
    elif corner_name == "bottom-left":
        window_x1, window_y1 = x1_index, max(y1_index, y2_index - window_height)
    else:
        window_x1, window_y1 = max(x1_index, x2_index - window_width), max(y1_index, y2_index - window_height)
    window_x2 = min(image_width, window_x1 + window_width)
    window_y2 = min(image_height, window_y1 + window_height)
    resolved_window_width = max(1, window_x2 - window_x1)
    resolved_window_height = max(1, window_y2 - window_y1)
    local_mask = np.ones((resolved_window_height, resolved_window_width), dtype=np.uint8)
    if window_shape == "triangle":
        y_grid, x_grid = np.mgrid[0:resolved_window_height, 0:resolved_window_width]
        normalized_x = x_grid / max(1, resolved_window_width - 1)
        normalized_y = y_grid / max(1, resolved_window_height - 1)
        if corner_name == "top-left":
            local_mask = (normalized_x + normalized_y <= 1.0).astype(np.uint8)
        elif corner_name == "top-right":
            local_mask = (((1.0 - normalized_x) + normalized_y) <= 1.0).astype(np.uint8)
        elif corner_name == "bottom-left":
            local_mask = ((normalized_x + (1.0 - normalized_y)) <= 1.0).astype(np.uint8)
        else:
            local_mask = (((1.0 - normalized_x) + (1.0 - normalized_y)) <= 1.0).astype(np.uint8)
    window_mask = np.zeros((image_height, image_width), dtype=np.uint8)
    window_mask[window_y1:window_y2, window_x1:window_x2] = local_mask
    return window_mask, [window_x1, window_y1, window_x2, window_y2]


def _read_corner_name(raw_value: object) -> str:
    """读取角点名称。"""

    if raw_value is None:
        return "top-right"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 corner 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 corner 仅支持 top-left、top-right、bottom-left 或 bottom-right")
    return normalized_value


def _read_window_ratio(raw_value: object) -> float:
    """读取角点窗口比例。"""

    if raw_value is None:
        return 0.25
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 window_ratio 必须是数值")
    normalized_value = float(raw_value)
    if normalized_value <= 0.0 or normalized_value > 0.5:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 window_ratio 必须在 0 到 0.5 之间")
    return normalized_value


def _read_min_corner_fill_ratio(raw_value: object) -> float:
    """读取最小角点填充率。"""

    if raw_value is None:
        return 0.8
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 min_corner_fill_ratio 必须是数值")
    normalized_value = float(raw_value)
    if normalized_value < 0.0 or normalized_value > 1.0:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 min_corner_fill_ratio 必须在 0 到 1 之间")
    return normalized_value


def _read_window_shape(raw_value: object) -> str:
    """读取角点窗口形状。"""

    if raw_value is None:
        return "triangle"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 window_shape 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"triangle", "rect"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 window_shape 仅支持 triangle 或 rect")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.corner-missing-check",
        display_name="Corner Missing Check",
        category="vision.defect",
        description="检查目标区域指定角点的局部填充率，适合板件缺角、零件崩角和外形角部损伤判定。",
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
                "corner": {
                    "type": "string",
                    "enum": ["top-left", "top-right", "bottom-left", "bottom-right"],
                    "default": "top-right",
                    "title": "角点",
                },
                "window_ratio": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 0.5,
                    "default": 0.25,
                    "title": "角点窗口比例",
                },
                "min_corner_fill_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0.8,
                    "title": "最小角点填充率",
                },
                "window_shape": {
                    "type": "string",
                    "enum": ["triangle", "rect"],
                    "default": "triangle",
                    "title": "窗口形状",
                },
            },
            "required": ["selector"],
        },
        capability_tags=("vision.defect", "inspection.corner", "inspection.corner.missing"),
    ),
    handler=_corner_missing_check_handler,
)
