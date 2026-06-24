"""Hough Lines 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.payloads import build_lines_payload
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.hough-lines"


def _read_positive_float(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取正浮点参数。"""

    if raw_value in {None, ""}:
        return float(default_value)
    normalized_value = require_non_negative_float(raw_value, field_name=field_name)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return float(normalized_value)


def _read_non_negative_float(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取非负浮点参数。"""

    if raw_value in {None, ""}:
        return float(default_value)
    return float(require_non_negative_float(raw_value, field_name=field_name))


def _read_threshold(raw_value: object) -> int:
    """读取 Hough threshold。"""

    if raw_value in {None, ""}:
        return 60
    return require_positive_int(raw_value, field_name="threshold")


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="limit")


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
        image_matrix,
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

    return {
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
