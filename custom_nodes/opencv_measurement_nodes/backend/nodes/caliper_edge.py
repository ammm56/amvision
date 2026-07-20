"""Caliper Edge 节点实现。"""

from __future__ import annotations

import json
import math
from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import require_roi_payload
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_line_overlay,
    build_numeric_control,
    build_select_control,
)
from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import build_lines_payload
from custom_nodes._opencv_shared.backend.runtime.performance import read_find_result_limit
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_odd_kernel_size,
    require_non_negative_float,
)


NODE_TYPE_ID = "custom.opencv.caliper-edge"
MAX_CALIPER_SAMPLE_PIXELS = 4_000_000


def _read_choice(raw_value: object, *, field_name: str, default: str, choices: set[str]) -> str:
    """读取字符串枚举参数。"""

    if is_empty_parameter(raw_value):
        return default
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in choices:
        raise InvalidRequestError(f"{field_name} 仅支持 {', '.join(sorted(choices))}")
    return normalized_value


def _read_positive_float(raw_value: object, *, field_name: str, default: float) -> float:
    """读取正浮点参数。"""

    if is_empty_parameter(raw_value):
        return default
    value = float(require_non_negative_float(raw_value, field_name=field_name))
    if value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return value


def _read_optional_line(raw_value: object) -> list[float] | None:
    """读取图片面板写回的 Caliper 搜索方向线。"""

    if is_empty_parameter(raw_value):
        return None
    parsed_value = raw_value
    if isinstance(raw_value, str):
        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise InvalidRequestError("line_xyxy 必须是 JSON 数组") from exc
    if not isinstance(parsed_value, list) or len(parsed_value) != 4:
        raise InvalidRequestError("line_xyxy 必须是 [x1, y1, x2, y2]")
    values: list[float] = []
    for item in parsed_value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise InvalidRequestError("line_xyxy 坐标必须是数值")
        value = float(item)
        if not math.isfinite(value):
            raise InvalidRequestError("line_xyxy 坐标必须是有限数值")
        values.append(value)
    if math.hypot(values[2] - values[0], values[3] - values[1]) < 2.0:
        raise InvalidRequestError("line_xyxy 长度至少为 2 像素")
    return values


def _clip_search_bbox(*, bbox_xyxy: list[float], image_width: int, image_height: int) -> list[int]:
    """把搜索 bbox 限制在图片范围内。"""

    x1_value = max(0, min(image_width - 1, int(round(float(bbox_xyxy[0])))))
    y1_value = max(0, min(image_height - 1, int(round(float(bbox_xyxy[1])))))
    x2_value = max(x1_value + 1, min(image_width, int(round(float(bbox_xyxy[2])))))
    y2_value = max(y1_value + 1, min(image_height, int(round(float(bbox_xyxy[3])))))
    return [x1_value, y1_value, x2_value, y2_value]


def _reduce_profile(*, image_matrix: Any, axis: int, reduction: str, np_module: Any) -> Any:
    """把 Caliper 采样矩阵归并为一维 profile。"""

    if reduction == "mean":
        return np_module.mean(image_matrix, axis=axis, dtype=np_module.float32)
    if reduction == "median":
        return np_module.median(image_matrix, axis=axis)
    if reduction == "max":
        return np_module.max(image_matrix, axis=axis)
    return np_module.min(image_matrix, axis=axis)


def _compute_gradient_scores(*, gradient_values: Any, polarity: str, np_module: Any) -> Any:
    """按边缘极性构造非负峰值分数。"""

    values = gradient_values.astype(np_module.float32, copy=False)
    if polarity == "any":
        return np_module.abs(values)
    if polarity == "dark-to-bright":
        return np_module.maximum(values, 0.0)
    return np_module.maximum(-values, 0.0)


def _select_peak_indices(
    scores: Any,
    *,
    threshold: float,
    min_distance: float,
    limit: int,
    np_module: Any,
) -> list[int]:
    """通过局部极大值和一维 NMS 选择稳定边缘。"""

    if int(scores.size) == 0:
        return []
    candidates: list[int] = []
    for index in range(int(scores.size)):
        score = float(scores[index])
        if score < threshold:
            continue
        left_score = float(scores[index - 1]) if index > 0 else float("-inf")
        right_score = float(scores[index + 1]) if index + 1 < int(scores.size) else float("-inf")
        if score >= left_score and score >= right_score:
            candidates.append(index)
    candidates.sort(key=lambda index: (-float(scores[index]), index))
    selected: list[int] = []
    for index in candidates:
        if any(abs(index - current_index) < min_distance for current_index in selected):
            continue
        selected.append(index)
        if len(selected) >= limit:
            break
    return sorted(selected)


def _refine_peak_coordinate(scores: Any, index: int) -> float:
    """用三点抛物线插值计算亚像素峰值位置。"""

    if index <= 0 or index + 1 >= int(scores.size):
        return float(index) + 0.5
    left_value = float(scores[index - 1])
    center_value = float(scores[index])
    right_value = float(scores[index + 1])
    denominator = left_value - 2.0 * center_value + right_value
    if abs(denominator) < 1e-9:
        return float(index) + 0.5
    delta = 0.5 * (left_value - right_value) / denominator
    return float(index) + 0.5 + max(-0.5, min(0.5, delta))


def _sample_line_caliper(
    image_matrix: Any,
    *,
    line_xyxy: list[float],
    caliper_width: float,
    cv2_module: Any,
    np_module: Any,
) -> tuple[Any, dict[str, float]]:
    """沿任意方向线生成 Caliper 采样矩阵。"""

    x1_value, y1_value, x2_value, y2_value = line_xyxy
    dx_value = x2_value - x1_value
    dy_value = y2_value - y1_value
    line_length = float(math.hypot(dx_value, dy_value))
    unit_x = dx_value / line_length
    unit_y = dy_value / line_length
    normal_x = -unit_y
    normal_y = unit_x
    length_samples = max(2, int(math.ceil(line_length)) + 1)
    width_samples = max(1, int(math.ceil(caliper_width)))
    if length_samples * width_samples > MAX_CALIPER_SAMPLE_PIXELS:
        raise InvalidRequestError(
            "Caliper 采样区域过大，请缩短搜索线或减小 Caliper Width",
            details={
                "sample_pixels": length_samples * width_samples,
                "max_sample_pixels": MAX_CALIPER_SAMPLE_PIXELS,
            },
        )
    along = np_module.linspace(0.0, line_length, length_samples, dtype=np_module.float32)
    across = np_module.linspace(
        -caliper_width / 2.0,
        caliper_width / 2.0,
        width_samples,
        dtype=np_module.float32,
    )
    map_x = x1_value + across[:, None] * normal_x + along[None, :] * unit_x
    map_y = y1_value + across[:, None] * normal_y + along[None, :] * unit_y
    sampled_matrix = cv2_module.remap(
        image_matrix,
        map_x.astype(np_module.float32),
        map_y.astype(np_module.float32),
        interpolation=cv2_module.INTER_LINEAR,
        borderMode=cv2_module.BORDER_REPLICATE,
    )
    return sampled_matrix, {
        "x1": x1_value,
        "y1": y1_value,
        "unit_x": unit_x,
        "unit_y": unit_y,
        "normal_x": normal_x,
        "normal_y": normal_y,
        "line_length": line_length,
        "sample_step": line_length / float(length_samples - 1),
    }


def _build_line_item(
    *,
    line_index: int,
    start_xy: list[float],
    end_xy: list[float],
    edge_strength: float,
    raw_gradient: float,
    profile_index: int,
    profile_coordinate: float,
    edge_polarity: str,
) -> dict[str, object]:
    """构造标准 lines.v1 item。"""

    dx_pixels = float(end_xy[0] - start_xy[0])
    dy_pixels = float(end_xy[1] - start_xy[1])
    midpoint_x = round((start_xy[0] + end_xy[0]) / 2.0, 4)
    midpoint_y = round((start_xy[1] + end_xy[1]) / 2.0, 4)
    angle_deg = float(math.degrees(math.atan2(dy_pixels, dx_pixels)) % 180.0)
    if angle_deg >= 90.0:
        angle_deg -= 180.0
    return {
        "line_index": line_index,
        "start_xy": [round(value, 4) for value in start_xy],
        "end_xy": [round(value, 4) for value in end_xy],
        "dx_pixels": round(dx_pixels, 4),
        "dy_pixels": round(dy_pixels, 4),
        "length_pixels": round(float(math.hypot(dx_pixels, dy_pixels)), 4),
        "angle_deg": round(angle_deg, 4),
        "midpoint_xy": [midpoint_x, midpoint_y],
        "midpoint_x": midpoint_x,
        "midpoint_y": midpoint_y,
        "bbox_xyxy": [
            round(min(start_xy[0], end_xy[0]), 4),
            round(min(start_xy[1], end_xy[1]), 4),
            round(max(start_xy[0], end_xy[0]), 4),
            round(max(start_xy[1], end_xy[1]), 4),
        ],
        "edge_strength": round(edge_strength, 4),
        "raw_gradient": round(raw_gradient, 4),
        "edge_polarity": edge_polarity,
        "profile_index": profile_index,
        "profile_coordinate": round(profile_coordinate, 4),
        "subpixel": True,
    }


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """在轴向 ROI 或任意方向 Caliper 中检测一个或多个边缘。"""

    cv2_module, np_module = require_opencv_imports()
    source_image_payload, source_object_key, image_matrix = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    image_height, image_width = [int(value) for value in image_matrix.shape[:2]]
    edge_orientation = _read_choice(
        request.parameters.get("edge_orientation"),
        field_name="edge_orientation",
        default="vertical",
        choices={"vertical", "horizontal"},
    )
    edge_polarity = _read_choice(
        request.parameters.get("edge_polarity"),
        field_name="edge_polarity",
        default="any",
        choices={"any", "dark-to-bright", "bright-to-dark"},
    )
    profile_reduction = _read_choice(
        request.parameters.get("profile_reduction"),
        field_name="profile_reduction",
        default="mean",
        choices={"mean", "median", "max", "min"},
    )
    smoothing_kernel_size = (
        5
        if is_empty_parameter(request.parameters.get("smoothing_kernel_size"))
        else int(normalize_odd_kernel_size(request.parameters.get("smoothing_kernel_size")))
    )
    gradient_threshold = float(
        require_non_negative_float(
            5.0 if is_empty_parameter(request.parameters.get("gradient_threshold")) else request.parameters.get("gradient_threshold"),
            field_name="gradient_threshold",
        )
    )
    min_edge_distance = _read_positive_float(
        request.parameters.get("min_edge_distance"),
        field_name="min_edge_distance",
        default=10.0,
    )
    max_results = read_find_result_limit(
        request.parameters.get("max_results"),
        field_name="max_results",
    )
    caliper_width = _read_positive_float(
        request.parameters.get("caliper_width"),
        field_name="caliper_width",
        default=20.0,
    )
    line_xyxy = _read_optional_line(request.parameters.get("line_xyxy"))

    raw_roi_payload = request.input_values.get("roi")
    roi_payload = require_roi_payload(raw_roi_payload, node_id=request.node_id) if raw_roi_payload is not None else None
    if roi_payload is not None and roi_payload["roi_kind"] == "polygon":
        raise InvalidRequestError("Caliper Edge 当前要求 bbox ROI；Polygon ROI 不能隐式按 bbox 处理")

    search_bbox_xyxy: list[int] | None = None
    if line_xyxy is not None:
        sampled_matrix, line_geometry = _sample_line_caliper(
            image_matrix,
            line_xyxy=line_xyxy,
            caliper_width=caliper_width,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        profile_axis = 0
        search_mode = "line"
    else:
        search_bbox_xyxy = (
            _clip_search_bbox(
                bbox_xyxy=roi_payload["bbox_xyxy"],
                image_width=image_width,
                image_height=image_height,
            )
            if roi_payload is not None
            else [0, 0, image_width, image_height]
        )
        x1_value, y1_value, x2_value, y2_value = search_bbox_xyxy
        sampled_matrix = image_matrix[y1_value:y2_value, x1_value:x2_value]
        profile_axis = 0 if edge_orientation == "vertical" else 1
        line_geometry = {}
        search_mode = "axis-aligned"

    if smoothing_kernel_size > 1:
        sampled_matrix = cv2_module.GaussianBlur(
            sampled_matrix,
            (smoothing_kernel_size, smoothing_kernel_size),
            0,
        )
    profile_values = _reduce_profile(
        image_matrix=sampled_matrix,
        axis=profile_axis,
        reduction=profile_reduction,
        np_module=np_module,
    ).astype(np_module.float32, copy=False)
    gradient_values = np_module.diff(profile_values)
    gradient_scores = _compute_gradient_scores(
        gradient_values=gradient_values,
        polarity=edge_polarity,
        np_module=np_module,
    )
    peak_indices = _select_peak_indices(
        gradient_scores,
        threshold=gradient_threshold,
        min_distance=min_edge_distance,
        limit=max_results,
        np_module=np_module,
    )

    line_items: list[dict[str, object]] = []
    for line_index, peak_index in enumerate(peak_indices, start=1):
        refined_coordinate = _refine_peak_coordinate(gradient_scores, peak_index)
        if search_mode == "line":
            distance = refined_coordinate * float(line_geometry["sample_step"])
            center_x = float(line_geometry["x1"]) + distance * float(line_geometry["unit_x"])
            center_y = float(line_geometry["y1"]) + distance * float(line_geometry["unit_y"])
            half_width = caliper_width / 2.0
            start_xy = [
                center_x - half_width * float(line_geometry["normal_x"]),
                center_y - half_width * float(line_geometry["normal_y"]),
            ]
            end_xy = [
                center_x + half_width * float(line_geometry["normal_x"]),
                center_y + half_width * float(line_geometry["normal_y"]),
            ]
        else:
            assert search_bbox_xyxy is not None
            search_x1, search_y1, search_x2, search_y2 = search_bbox_xyxy
            if edge_orientation == "vertical":
                coordinate = float(search_x1) + refined_coordinate
                start_xy = [coordinate, float(search_y1)]
                end_xy = [coordinate, float(search_y2)]
            else:
                coordinate = float(search_y1) + refined_coordinate
                start_xy = [float(search_x1), coordinate]
                end_xy = [float(search_x2), coordinate]
        line_items.append(
            _build_line_item(
                line_index=line_index,
                start_xy=start_xy,
                end_xy=end_xy,
                edge_strength=float(gradient_scores[peak_index]),
                raw_gradient=float(gradient_values[peak_index]),
                profile_index=peak_index,
                profile_coordinate=refined_coordinate,
                edge_polarity=edge_polarity,
            )
        )

    best_line_item = max(line_items, key=lambda item: float(item["edge_strength"]), default=None)
    summary_value: dict[str, object] = {
        "found": bool(line_items),
        "line_count": len(line_items),
        "search_mode": search_mode,
        "line_xyxy": line_xyxy,
        "search_bbox_xyxy": search_bbox_xyxy,
        "edge_orientation": edge_orientation,
        "edge_polarity": edge_polarity,
        "profile_reduction": profile_reduction,
        "smoothing_kernel_size": smoothing_kernel_size,
        "gradient_threshold": gradient_threshold,
        "min_edge_distance": min_edge_distance,
        "max_results": max_results,
        "caliper_width": caliper_width,
        "profile_length": int(profile_values.shape[0]),
        "max_edge_strength": round(max((float(item["edge_strength"]) for item in line_items), default=0.0), 4),
        "best_edge_coordinate": (
            float(best_line_item["profile_coordinate"])
            + (
                float(search_bbox_xyxy[0] if edge_orientation == "vertical" else search_bbox_xyxy[1])
                if search_mode == "axis-aligned" and search_bbox_xyxy is not None
                else 0.0
            )
            if best_line_item is not None
            else None
        ),
    }
    if roi_payload is not None:
        summary_value.update(
            {
                "roi_id": roi_payload.get("roi_id"),
                "roi_kind": roi_payload.get("roi_kind"),
                "roi_polygon_bbox_only": False,
            }
        )
    outputs: dict[str, object] = {
        "lines": build_lines_payload(
            items=line_items,
            source_image=source_image_payload,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(summary_value),
    }
    overlays = [
        build_line_overlay(
            overlay_id=f"caliper-edge-{item['line_index']}",
            label=f"edge {item['line_index']}",
            line_xyxy=[*item["start_xy"], *item["end_xy"]],
        )
        for item in line_items
    ]
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=source_image_payload,
            title="Caliper Edge",
            artifact_name="caliper-edge-debug-preview",
            overlays=overlays,
            interaction=build_debug_panel_interaction(
                tools=[build_interaction_tool("line", "Caliper Line", ["line_xyxy"])],
                controls=[
                    build_numeric_control("caliper_width", "Caliper Width", caliper_width, min_value=1.0, max_value=float(max(image_width, image_height)), step=1.0),
                    build_select_control(
                        "edge_polarity",
                        "Edge Polarity",
                        edge_polarity,
                        options=[("any", "Any"), ("dark-to-bright", "Dark To Bright"), ("bright-to-dark", "Bright To Dark")],
                    ),
                    build_numeric_control("gradient_threshold", "Gradient Threshold", gradient_threshold, min_value=0.0, max_value=255.0, step=1.0),
                    build_numeric_control("min_edge_distance", "Min Edge Distance", min_edge_distance, min_value=1.0, max_value=float(max(image_width, image_height)), step=1.0),
                    build_numeric_control("max_results", "Max Results", max_results, min_value=1.0, max_value=1000.0, step=1.0),
                ],
            ),
        )
    )
    return outputs
