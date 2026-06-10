"""Caliper Edge 节点实现。"""

from __future__ import annotations

import math
from typing import Any

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._roi_node_support import require_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_lines_payload,
    load_image_matrix,
    normalize_odd_kernel_size,
    require_non_negative_float,
    require_opencv_imports,
)


NODE_TYPE_ID = "custom.opencv.caliper-edge"


def _read_edge_orientation(raw_value: object) -> str:
    """读取边方向。"""

    if raw_value in {None, ""}:
        return "vertical"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("edge_orientation 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"vertical", "horizontal"}:
        raise InvalidRequestError("edge_orientation 仅支持 vertical 或 horizontal")
    return normalized_value


def _read_edge_polarity(raw_value: object) -> str:
    """读取边极性。"""

    if raw_value in {None, ""}:
        return "any"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("edge_polarity 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"any", "dark-to-bright", "bright-to-dark"}:
        raise InvalidRequestError("edge_polarity 仅支持 any、dark-to-bright 或 bright-to-dark")
    return normalized_value


def _read_profile_reduction(raw_value: object) -> str:
    """读取投影归并方式。"""

    if raw_value in {None, ""}:
        return "mean"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("profile_reduction 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"mean", "median", "max", "min"}:
        raise InvalidRequestError("profile_reduction 仅支持 mean、median、max 或 min")
    return normalized_value


def _read_gradient_threshold(raw_value: object) -> float:
    """读取最小梯度阈值。"""

    if raw_value in {None, ""}:
        return 5.0
    return float(require_non_negative_float(raw_value, field_name="gradient_threshold"))


def _read_smoothing_kernel_size(raw_value: object) -> int:
    """读取平滑核大小。"""

    if raw_value in {None, ""}:
        return 5
    return int(normalize_odd_kernel_size(raw_value))


def _clip_search_bbox(
    *,
    bbox_xyxy: list[float],
    image_width: int,
    image_height: int,
) -> list[int]:
    """把搜索 bbox 限制在图片范围内。"""

    x1_value = max(0, min(image_width - 1, int(round(float(bbox_xyxy[0])))))
    y1_value = max(0, min(image_height - 1, int(round(float(bbox_xyxy[1])))))
    x2_value = max(x1_value + 1, min(image_width, int(round(float(bbox_xyxy[2])))))
    y2_value = max(y1_value + 1, min(image_height, int(round(float(bbox_xyxy[3])))))
    return [x1_value, y1_value, x2_value, y2_value]


def _extract_search_matrix(
    *,
    image_matrix: Any,
    roi_payload: dict[str, object] | None,
) -> tuple[Any, list[int], bool]:
    """解析搜索窗口。"""

    image_height = int(image_matrix.shape[0])
    image_width = int(image_matrix.shape[1])
    if roi_payload is None:
        return image_matrix, [0, 0, image_width, image_height], False
    search_bbox_xyxy = _clip_search_bbox(
        bbox_xyxy=roi_payload["bbox_xyxy"],
        image_width=image_width,
        image_height=image_height,
    )
    x1_value, y1_value, x2_value, y2_value = search_bbox_xyxy
    return (
        image_matrix[y1_value:y2_value, x1_value:x2_value],
        search_bbox_xyxy,
        roi_payload["roi_kind"] == "polygon",
    )


def _reduce_profile(*, image_matrix: Any, edge_orientation: str, profile_reduction: str, np_module: Any) -> Any:
    """把 ROI 图片规整成单条一维 profile。"""

    axis_value = 0 if edge_orientation == "vertical" else 1
    if profile_reduction == "mean":
        return np_module.mean(image_matrix, axis=axis_value, dtype=np_module.float32)
    if profile_reduction == "median":
        return np_module.median(image_matrix, axis=axis_value)
    if profile_reduction == "max":
        return np_module.max(image_matrix, axis=axis_value)
    return np_module.min(image_matrix, axis=axis_value)


def _normalize_angle_deg(*, dx_pixels: float, dy_pixels: float) -> float:
    """把线段方向角规整到无方向语义。"""

    angle_deg = float(math.degrees(math.atan2(dy_pixels, dx_pixels)))
    angle_deg = float(angle_deg % 180.0)
    if angle_deg >= 90.0:
        angle_deg -= 180.0
    return round(angle_deg, 4)


def _compute_gradient_scores(*, gradient_values: Any, edge_polarity: str, np_module: Any) -> tuple[Any, float]:
    """根据边极性把梯度规整成可比较分数。"""

    normalized_gradient = gradient_values.astype(np_module.float32, copy=False)
    if edge_polarity == "any":
        return np_module.abs(normalized_gradient), 1.0
    if edge_polarity == "dark-to-bright":
        return np_module.maximum(normalized_gradient, 0.0), 1.0
    return np_module.maximum(-normalized_gradient, 0.0), -1.0


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """在 ROI 内按单轴 profile 检测最强边缘，并输出 lines.v1。"""

    cv2_module, np_module = require_opencv_imports()
    source_image_payload, source_object_key, image_matrix = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )

    edge_orientation = _read_edge_orientation(request.parameters.get("edge_orientation"))
    edge_polarity = _read_edge_polarity(request.parameters.get("edge_polarity"))
    profile_reduction = _read_profile_reduction(request.parameters.get("profile_reduction"))
    smoothing_kernel_size = _read_smoothing_kernel_size(request.parameters.get("smoothing_kernel_size"))
    gradient_threshold = _read_gradient_threshold(request.parameters.get("gradient_threshold"))

    raw_roi_payload = request.input_values.get("roi")
    roi_payload = require_roi_payload(raw_roi_payload, node_id=request.node_id) if raw_roi_payload is not None else None
    search_image_matrix, search_bbox_xyxy, roi_polygon_bbox_only = _extract_search_matrix(
        image_matrix=image_matrix,
        roi_payload=roi_payload,
    )
    search_height = int(search_image_matrix.shape[0])
    search_width = int(search_image_matrix.shape[1])
    if search_width < 2 and edge_orientation == "vertical":
        raise InvalidRequestError("vertical caliper-edge 要求搜索区域宽度至少为 2")
    if search_height < 2 and edge_orientation == "horizontal":
        raise InvalidRequestError("horizontal caliper-edge 要求搜索区域高度至少为 2")

    if smoothing_kernel_size > 1:
        smoothed_matrix = cv2_module.GaussianBlur(
            search_image_matrix,
            (smoothing_kernel_size, smoothing_kernel_size),
            0,
        )
    else:
        smoothed_matrix = search_image_matrix

    profile_values = _reduce_profile(
        image_matrix=smoothed_matrix,
        edge_orientation=edge_orientation,
        profile_reduction=profile_reduction,
        np_module=np_module,
    ).astype(np_module.float32, copy=False)
    gradient_values = np_module.diff(profile_values)
    gradient_scores, gradient_sign = _compute_gradient_scores(
        gradient_values=gradient_values,
        edge_polarity=edge_polarity,
        np_module=np_module,
    )

    profile_length = int(profile_values.shape[0])
    best_index = int(np_module.argmax(gradient_scores)) if gradient_scores.size > 0 else -1
    best_score = float(gradient_scores[best_index]) if best_index >= 0 else 0.0
    raw_gradient_value = float(gradient_values[best_index]) if best_index >= 0 else 0.0
    found = best_index >= 0 and best_score >= gradient_threshold

    line_items: list[dict[str, object]] = []
    edge_coordinate: float | None = None
    if found:
        edge_coordinate_local = float(best_index) + 0.5
        search_x1, search_y1, search_x2, search_y2 = search_bbox_xyxy
        if edge_orientation == "vertical":
            edge_coordinate = float(search_x1) + edge_coordinate_local
            start_xy = [round(edge_coordinate, 4), float(search_y1)]
            end_xy = [round(edge_coordinate, 4), float(search_y2)]
        else:
            edge_coordinate = float(search_y1) + edge_coordinate_local
            start_xy = [float(search_x1), round(edge_coordinate, 4)]
            end_xy = [float(search_x2), round(edge_coordinate, 4)]
        dx_pixels = float(end_xy[0] - start_xy[0])
        dy_pixels = float(end_xy[1] - start_xy[1])
        midpoint_x = round((float(start_xy[0]) + float(end_xy[0])) / 2.0, 4)
        midpoint_y = round((float(start_xy[1]) + float(end_xy[1])) / 2.0, 4)
        line_items.append(
            {
                "line_index": 1,
                "start_xy": [round(float(start_xy[0]), 4), round(float(start_xy[1]), 4)],
                "end_xy": [round(float(end_xy[0]), 4), round(float(end_xy[1]), 4)],
                "dx_pixels": round(dx_pixels, 4),
                "dy_pixels": round(dy_pixels, 4),
                "length_pixels": round(float(math.hypot(dx_pixels, dy_pixels)), 4),
                "angle_deg": _normalize_angle_deg(dx_pixels=dx_pixels, dy_pixels=dy_pixels),
                "midpoint_xy": [midpoint_x, midpoint_y],
                "midpoint_x": midpoint_x,
                "midpoint_y": midpoint_y,
                "bbox_xyxy": [
                    round(min(float(start_xy[0]), float(end_xy[0])), 4),
                    round(min(float(start_xy[1]), float(end_xy[1])), 4),
                    round(max(float(start_xy[0]), float(end_xy[0])), 4),
                    round(max(float(start_xy[1]), float(end_xy[1])), 4),
                ],
                "edge_strength": round(best_score, 4),
                "raw_gradient": round(raw_gradient_value, 4),
                "edge_orientation": edge_orientation,
                "edge_polarity": edge_polarity,
                "profile_index": int(best_index),
                "profile_coordinate": round(edge_coordinate_local, 4),
            }
        )

    summary_payload = {
        "found": found,
        "edge_orientation": edge_orientation,
        "edge_polarity": edge_polarity,
        "profile_reduction": profile_reduction,
        "smoothing_kernel_size": smoothing_kernel_size,
        "gradient_threshold": gradient_threshold,
        "search_bbox_xyxy": [int(value) for value in search_bbox_xyxy],
        "search_width": search_width,
        "search_height": search_height,
        "profile_length": profile_length,
        "best_profile_index": int(best_index) if best_index >= 0 else None,
        "best_profile_coordinate": round(float(best_index) + 0.5, 4) if best_index >= 0 else None,
        "best_edge_coordinate": round(edge_coordinate, 4) if edge_coordinate is not None else None,
        "best_edge_strength": round(best_score, 4),
        "best_raw_gradient": round(raw_gradient_value, 4),
        "gradient_sign": gradient_sign,
        "line_count": len(line_items),
    }
    if roi_payload is not None:
        summary_payload["roi_id"] = roi_payload["roi_id"]
        summary_payload["roi_kind"] = roi_payload["roi_kind"]
        summary_payload["roi_bbox_xyxy"] = [round(float(value), 4) for value in roi_payload["bbox_xyxy"]]
        summary_payload["roi_polygon_bbox_only"] = roi_polygon_bbox_only

    return {
        "lines": build_lines_payload(
            items=line_items,
            source_image=source_image_payload,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(summary_payload),
    }
