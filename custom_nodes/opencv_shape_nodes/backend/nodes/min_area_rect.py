"""Min Area Rect 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.geometry import compute_contour_metrics_from_points
from custom_nodes._opencv_shared.backend.runtime.payloads import require_contours_payload
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.validators import require_positive_int


NODE_TYPE_ID = "custom.opencv.min-area-rect"


def _normalize_sort_by(value: object) -> str:
    """规范化 min-area-rect 的排序字段。"""

    if not isinstance(value, str) or not value.strip():
        return "contour_index"
    normalized_value = value.strip().lower()
    if normalized_value not in {
        "contour_index",
        "contour_area",
        "rect_area",
        "long_side",
        "short_side",
        "angle_deg",
        "fill_ratio",
    }:
        raise InvalidRequestError("sort_by 不在支持的 min-area-rect 排序字段列表中")
    return normalized_value


def _normalize_angle_deg(*, width_value: float, height_value: float, angle_value: float) -> float:
    """把 OpenCV minAreaRect angle 规整到更稳定的角度语义。"""

    normalized_angle = float(angle_value if width_value >= height_value else angle_value + 90.0)
    normalized_angle = float(normalized_angle % 180.0)
    if normalized_angle >= 90.0:
        normalized_angle -= 180.0
    return round(float(normalized_angle), 4)


def _build_rotated_rects_payload(
    *,
    items: list[dict[str, object]],
    source_image: object | None,
    source_object_key: str | None,
) -> dict[str, object]:
    """构建 rotated-rects.v1 payload。"""

    payload: dict[str, object] = {
        "items": [dict(item) for item in items],
        "count": len(items),
    }
    if isinstance(source_image, dict):
        payload["source_image"] = dict(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    return payload


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 contour 集合计算最小外接旋转矩形。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    sort_by = _normalize_sort_by(request.parameters.get("sort_by"))
    descending = bool(request.parameters.get("descending", False))
    raw_limit = request.parameters.get("limit")
    limit = None if raw_limit in {None, ""} else require_positive_int(raw_limit, field_name="limit")

    rotated_rect_items: list[dict[str, object]] = []
    for contour_item in contours_payload["items"]:
        contour_points = np_module.array(contour_item["points"], dtype=np_module.float32)
        contour_metrics = compute_contour_metrics_from_points(
            points=contour_item["points"],
            cv2_module=cv2_module,
            np_module=np_module,
        )
        center_xy, size_wh, angle_value = cv2_module.minAreaRect(contour_points)
        rect_width = round(float(size_wh[0]), 4)
        rect_height = round(float(size_wh[1]), 4)
        long_side = round(max(rect_width, rect_height), 4)
        short_side = round(min(rect_width, rect_height), 4)
        rect_area = round(float(rect_width * rect_height), 4)
        contour_area = round(float(contour_metrics["area"]), 4)
        fill_ratio = round(float(contour_area / rect_area), 4) if rect_area > 0 else 0.0
        box_points = cv2_module.boxPoints((center_xy, size_wh, angle_value)).tolist()
        bbox_x_values = [float(point[0]) for point in box_points]
        bbox_y_values = [float(point[1]) for point in box_points]
        rotated_rect_items.append(
            {
                "contour_index": int(contour_item["contour_index"]),
                "point_count": int(contour_item["point_count"]),
                "center_xy": [round(float(center_xy[0]), 4), round(float(center_xy[1]), 4)],
                "size_wh": [rect_width, rect_height],
                "width": rect_width,
                "height": rect_height,
                "long_side": long_side,
                "short_side": short_side,
                "angle_deg": _normalize_angle_deg(
                    width_value=rect_width,
                    height_value=rect_height,
                    angle_value=float(angle_value),
                ),
                "bbox_xyxy": [
                    round(min(bbox_x_values), 4),
                    round(min(bbox_y_values), 4),
                    round(max(bbox_x_values), 4),
                    round(max(bbox_y_values), 4),
                ],
                "box_points": [
                    [round(float(point[0]), 4), round(float(point[1]), 4)]
                    for point in box_points
                ],
                "contour_area": contour_area,
                "rect_area": rect_area,
                "fill_ratio": fill_ratio,
            }
        )

    rotated_rect_items.sort(key=lambda current_item: current_item[sort_by], reverse=descending)
    if limit is not None:
        rotated_rect_items = rotated_rect_items[:limit]

    return {
        "rotated_rects": _build_rotated_rects_payload(
            items=rotated_rect_items,
            source_image=contours_payload.get("source_image"),
            source_object_key=contours_payload.get("source_object_key")
            if isinstance(contours_payload.get("source_object_key"), str)
            else None,
        ),
        "summary": build_value_payload(
            {
                "count": len(rotated_rect_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "max_long_side": round(max((float(item["long_side"]) for item in rotated_rect_items), default=0.0), 4),
                "max_rect_area": round(max((float(item["rect_area"]) for item in rotated_rect_items), default=0.0), 4),
                "mean_fill_ratio": round(
                    (
                        sum(float(item["fill_ratio"]) for item in rotated_rect_items) / len(rotated_rect_items)
                        if rotated_rect_items
                        else 0.0
                    ),
                    4,
                ),
            }
        ),
    }
