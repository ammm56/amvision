"""Measure 节点实现。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    require_contours_payload,
    require_opencv_imports,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.measure"


def _normalize_sort_by(value: object) -> str:
    """规范化 measure 节点的排序字段。

    参数：
    - value：原始排序字段。

    返回：
    - str：规范化后的排序字段名称。
    """

    if not isinstance(value, str) or not value.strip():
        return "contour_index"
    normalized_value = value.strip().lower()
    if normalized_value not in {"contour_index", "area", "perimeter", "width", "height"}:
        raise InvalidRequestError("sort_by 不在支持的 measure 排序字段列表中")
    return normalized_value


def _build_measurement_item(*, contour_item: dict[str, object], cv2_module: Any, np_module: Any) -> dict[str, object]:
    """根据单个 contour item 计算结构化度量结果。

    参数：
    - contour_item：单个 contour payload 项。
    - cv2_module：OpenCV 模块。
    - np_module：NumPy 模块。

    返回：
    - dict[str, object]：单个 contour 的度量结果。
    """

    contour_points = contour_item["points"]
    contour_matrix = np_module.array(contour_points, dtype=np_module.int32).reshape((-1, 1, 2))
    bbox_xyxy = list(contour_item["bbox_xyxy"])
    bbox_width = max(0, int(bbox_xyxy[2]) - int(bbox_xyxy[0]))
    bbox_height = max(0, int(bbox_xyxy[3]) - int(bbox_xyxy[1]))
    area = round(float(cv2_module.contourArea(contour_matrix)), 4)
    perimeter = round(float(cv2_module.arcLength(contour_matrix, True)), 4)
    center_x = round((float(bbox_xyxy[0]) + float(bbox_xyxy[2])) / 2.0, 4)
    center_y = round((float(bbox_xyxy[1]) + float(bbox_xyxy[3])) / 2.0, 4)
    aspect_ratio = round(float(bbox_width / bbox_height), 4) if bbox_height > 0 else 0.0
    return {
        "contour_index": int(contour_item["contour_index"]),
        "point_count": int(contour_item["point_count"]),
        "bbox_xyxy": bbox_xyxy,
        "width": bbox_width,
        "height": bbox_height,
        "area": area,
        "perimeter": perimeter,
        "center_xy": [center_x, center_y],
        "aspect_ratio": aspect_ratio,
    }


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入 contour 集合执行度量汇总，并输出结构化 measurement 集合。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    measurement_items = [
        _build_measurement_item(contour_item=item, cv2_module=cv2_module, np_module=np_module)
        for item in contours_payload["items"]
    ]

    sort_by = _normalize_sort_by(request.parameters.get("sort_by", "contour_index"))
    descending = bool(request.parameters.get("descending", False))
    measurement_items.sort(key=lambda current_item: current_item[sort_by], reverse=descending)

    limit_raw = request.parameters.get("limit")
    if limit_raw is not None:
        limit = require_positive_int(limit_raw, field_name="limit")
        measurement_items = measurement_items[:limit]

    total_area = round(sum(float(item["area"]) for item in measurement_items), 4)
    summary = {
        "total_area": total_area,
        "mean_area": round(total_area / len(measurement_items), 4) if measurement_items else 0.0,
        "max_area": round(max((float(item["area"]) for item in measurement_items), default=0.0), 4),
        "min_area": round(min((float(item["area"]) for item in measurement_items), default=0.0), 4),
    }
    return {
        "measurements": {
            "items": measurement_items,
            "count": len(measurement_items),
            "source_object_key": contours_payload.get("source_object_key"),
            "summary": summary,
        }
    }