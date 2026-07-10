"""Hough Lines 节点实现。"""

from __future__ import annotations

import json
import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import build_debug_image_preview_output
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import build_lines_payload
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.hough-lines"


def _read_positive_float(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取正浮点参数。"""

    if raw_value is None or raw_value == "":
        return float(default_value)
    normalized_value = require_non_negative_float(raw_value, field_name=field_name)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return float(normalized_value)


def _read_non_negative_float(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取非负浮点参数。"""

    if raw_value is None or raw_value == "":
        return float(default_value)
    return float(require_non_negative_float(raw_value, field_name=field_name))


def _read_threshold(raw_value: object) -> int:
    """读取 Hough threshold。"""

    if raw_value is None or raw_value == "":
        return 60
    return require_positive_int(raw_value, field_name="threshold")


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if raw_value is None or raw_value == "":
        return None
    return require_positive_int(raw_value, field_name="limit")


def _read_optional_bbox_xyxy(raw_value: object) -> list[float] | None:
    """读取可选搜索 ROI，格式为 [x1, y1, x2, y2]。"""

    if raw_value is None or raw_value == "":
        return None
    parsed_value = raw_value
    if isinstance(raw_value, str):
        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise InvalidRequestError("search_bbox_xyxy 必须是 JSON 数组") from exc
    if not isinstance(parsed_value, list) or len(parsed_value) != 4:
        raise InvalidRequestError("search_bbox_xyxy 必须是 [x1, y1, x2, y2]")
    bbox_values: list[float] = []
    for item in parsed_value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise InvalidRequestError("search_bbox_xyxy 的坐标必须是数值")
        value = float(item)
        if not math.isfinite(value):
            raise InvalidRequestError("search_bbox_xyxy 的坐标必须是有限数值")
        bbox_values.append(value)
    x1_value, y1_value, x2_value, y2_value = bbox_values
    if x2_value <= x1_value or y2_value <= y1_value:
        raise InvalidRequestError("search_bbox_xyxy 必须满足 x2 > x1 且 y2 > y1")
    return bbox_values


def _crop_search_image(image_matrix: object, *, search_bbox_xyxy: list[float] | None) -> tuple[object, int, int]:
    """按搜索 ROI 裁剪 Hough 输入图，并返回坐标偏移。"""

    if search_bbox_xyxy is None:
        return image_matrix, 0, 0
    image_height, image_width = image_matrix.shape[:2]
    x1_value = max(0, min(int(math.floor(search_bbox_xyxy[0])), image_width - 1))
    y1_value = max(0, min(int(math.floor(search_bbox_xyxy[1])), image_height - 1))
    x2_value = max(x1_value + 1, min(int(math.ceil(search_bbox_xyxy[2])), image_width))
    y2_value = max(y1_value + 1, min(int(math.ceil(search_bbox_xyxy[3])), image_height))
    return image_matrix[y1_value:y2_value, x1_value:x2_value], x1_value, y1_value


def _normalize_sort_by(value: object) -> str:
    """规范化 hough-lines 的排序字段。"""

    if not isinstance(value, str) or not value.strip():
        return "length_pixels"
    normalized_value = value.strip().lower()
    if normalized_value not in {
        "line_index",
        "length_pixels",
        "angle_deg",
        "midpoint_x",
        "midpoint_y",
    }:
        raise InvalidRequestError("sort_by 不在支持的 hough-lines 排序字段列表中")
    return normalized_value


def _normalize_angle_deg(*, dx_pixels: float, dy_pixels: float) -> float:
    """把线段方向角规整到更稳定的无方向语义。"""

    angle_deg = float(math.degrees(math.atan2(dy_pixels, dx_pixels)))
    angle_deg = float(angle_deg % 180.0)
    if angle_deg >= 90.0:
        angle_deg -= 180.0
    return round(angle_deg, 4)


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行概率 Hough 直线检测。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, source_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    search_bbox_xyxy = _read_optional_bbox_xyxy(request.parameters.get("search_bbox_xyxy"))
    search_image_matrix, search_offset_x, search_offset_y = _crop_search_image(
        image_matrix,
        search_bbox_xyxy=search_bbox_xyxy,
    )
    rho_resolution = _read_positive_float(
        request.parameters.get("rho_resolution"),
        field_name="rho_resolution",
        default_value=1.0,
    )
    theta_step_deg = _read_positive_float(
        request.parameters.get("theta_step_deg"),
        field_name="theta_step_deg",
        default_value=1.0,
    )
    threshold = _read_threshold(request.parameters.get("threshold"))
    min_line_length = _read_non_negative_float(
        request.parameters.get("min_line_length"),
        field_name="min_line_length",
        default_value=20.0,
    )
    max_line_gap = _read_non_negative_float(
        request.parameters.get("max_line_gap"),
        field_name="max_line_gap",
        default_value=5.0,
    )
    sort_by = _normalize_sort_by(request.parameters.get("sort_by"))
    descending = bool(request.parameters.get("descending", True))
    limit = _read_optional_limit(request.parameters.get("limit"))

    raw_lines = cv2_module.HoughLinesP(
        search_image_matrix,
        rho=rho_resolution,
        theta=math.radians(theta_step_deg),
        threshold=threshold,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )
    line_items: list[dict[str, object]] = []
    if raw_lines is not None:
        for line_index, raw_line in enumerate(raw_lines, start=1):
            x1_value, y1_value, x2_value, y2_value = [int(raw_value) for raw_value in raw_line.reshape(-1).tolist()[:4]]
            x1_value += search_offset_x
            x2_value += search_offset_x
            y1_value += search_offset_y
            y2_value += search_offset_y
            dx_pixels = float(x2_value - x1_value)
            dy_pixels = float(y2_value - y1_value)
            length_pixels = round(float(math.hypot(dx_pixels, dy_pixels)), 4)
            angle_deg = _normalize_angle_deg(dx_pixels=dx_pixels, dy_pixels=dy_pixels)
            midpoint_x = round((float(x1_value) + float(x2_value)) / 2.0, 4)
            midpoint_y = round((float(y1_value) + float(y2_value)) / 2.0, 4)
            line_items.append(
                {
                    "line_index": int(line_index),
                    "start_xy": [int(x1_value), int(y1_value)],
                    "end_xy": [int(x2_value), int(y2_value)],
                    "dx_pixels": round(dx_pixels, 4),
                    "dy_pixels": round(dy_pixels, 4),
                    "length_pixels": length_pixels,
                    "angle_deg": angle_deg,
                    "midpoint_xy": [midpoint_x, midpoint_y],
                    "midpoint_x": midpoint_x,
                    "midpoint_y": midpoint_y,
                    "bbox_xyxy": [
                        int(min(x1_value, x2_value)),
                        int(min(y1_value, y2_value)),
                        int(max(x1_value, x2_value)),
                        int(max(y1_value, y2_value)),
                    ],
                }
            )

    line_items.sort(key=lambda current_item: current_item[sort_by], reverse=descending)
    if limit is not None:
        line_items = line_items[:limit]

    outputs: dict[str, object] = {
        "lines": build_lines_payload(
            items=line_items,
            source_image=image_payload,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(
            {
                "count": len(line_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "rho_resolution": rho_resolution,
                "theta_step_deg": theta_step_deg,
                "threshold": threshold,
                "min_line_length": min_line_length,
                "max_line_gap": max_line_gap,
                "search_bbox_xyxy": search_bbox_xyxy,
                "max_length_pixels": round(
                    max((float(item["length_pixels"]) for item in line_items), default=0.0),
                    4,
                ),
                "mean_length_pixels": round(
                    (
                        sum(float(item["length_pixels"]) for item in line_items) / len(line_items)
                        if line_items
                        else 0.0
                    ),
                    4,
                ),
            }
        ),
    }
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=image_payload,
            title="Hough Lines",
            artifact_name="hough-lines-debug-preview",
            overlays=_build_line_overlays(line_items, search_bbox_xyxy=search_bbox_xyxy),
            interaction=_build_line_interaction(
                rho_resolution=rho_resolution,
                theta_step_deg=theta_step_deg,
                threshold=threshold,
                min_line_length=min_line_length,
                max_line_gap=max_line_gap,
            ),
        )
    )
    return outputs


def _build_line_interaction(
    *,
    rho_resolution: float,
    theta_step_deg: float,
    threshold: int,
    min_line_length: float,
    max_line_gap: float,
) -> dict[str, object]:
    """声明 Hough Lines 在图片面板中的取参和调参能力。"""

    return {
        "mode": "edit",
        "coordinate_space": "source-image",
        "tools": [
            {
                "tool": "line",
                "label": "找线",
                "target_parameters": ["min_line_length"],
            },
            {
                "tool": "bbox",
                "label": "搜索 ROI",
                "target_parameters": ["search_bbox_xyxy"],
            },
        ],
        "controls": [
            _build_numeric_control("rho_resolution", "Rho Resolution", rho_resolution, min_value=0.1, max_value=10.0, step=0.1),
            _build_numeric_control("theta_step_deg", "Theta Step Deg", theta_step_deg, min_value=0.1, max_value=10.0, step=0.1),
            _build_numeric_control("threshold", "Threshold", threshold, min_value=1.0, max_value=300.0, step=1.0),
            _build_numeric_control("min_line_length", "Min Line Length", min_line_length, min_value=0.0, max_value=1200.0, step=1.0),
            _build_numeric_control("max_line_gap", "Max Line Gap", max_line_gap, min_value=0.0, max_value=300.0, step=1.0),
        ],
    }


def _build_numeric_control(
    parameter_name: str,
    label: str,
    value: float | int,
    *,
    min_value: float,
    max_value: float,
    step: float,
) -> dict[str, object]:
    """构造图片面板实时调参使用的数值控件声明。"""

    return {
        "parameter_name": parameter_name,
        "label": label,
        "control": "slider",
        "min": min_value,
        "max": max_value,
        "step": step,
        "value": value,
        "default_value": value,
    }


def _build_line_overlays(
    line_items: list[dict[str, object]],
    *,
    search_bbox_xyxy: list[float] | None,
) -> list[dict[str, object]]:
    """把 Hough 直线检测结果转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    if search_bbox_xyxy is not None:
        overlays.append(
            {
                "kind": "bbox",
                "id": "search-roi",
                "label": "Search ROI",
                "bbox_xyxy": search_bbox_xyxy,
                "target_parameters": ["search_bbox_xyxy"],
            }
        )
    for line_item in line_items:
        start_xy = line_item.get("start_xy")
        end_xy = line_item.get("end_xy")
        if not isinstance(start_xy, list) or len(start_xy) < 2 or not isinstance(end_xy, list) or len(end_xy) < 2:
            continue
        line_index = line_item.get("line_index", len(overlays) + 1)
        overlays.append(
            {
                "kind": "line",
                "id": f"line-{line_index}",
                "label": f"line {line_index}",
                "line_xyxy": [
                    float(start_xy[0]),
                    float(start_xy[1]),
                    float(end_xy[0]),
                    float(end_xy[1]),
                ],
            }
        )
    return overlays
