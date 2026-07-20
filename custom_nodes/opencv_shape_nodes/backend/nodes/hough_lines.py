"""Hough Lines 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_checkbox_control,
    build_line_overlay,
    build_numeric_control,
    build_select_control,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.performance import (
    build_processing_image,
    build_processing_summary,
    read_find_result_limit,
    read_processing_max_long_edge,
)
from custom_nodes._opencv_shared.backend.runtime.payloads import build_lines_payload
from custom_nodes._opencv_shared.backend.runtime.search_roi import (
    ResolvedSearchRoi,
    build_search_roi_overlay,
    build_search_roi_summary,
    resolve_search_roi,
)
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


def _read_input_mode(raw_value: object) -> str:
    """读取 Hough Lines 输入预处理模式。"""

    if raw_value is None or raw_value == "":
        return "auto-canny"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("input_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"auto-canny", "binary-edge"}:
        raise InvalidRequestError("input_mode 仅支持 auto-canny 或 binary-edge")
    return normalized_value


def _read_canny_threshold(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取 Hough Lines 内置 Canny 阈值。"""

    value = _read_non_negative_float(raw_value, field_name=field_name, default_value=default_value)
    if value > 255:
        raise InvalidRequestError(f"{field_name} 不能大于 255")
    return value


def _read_boolean(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数，避免字符串被 Python 隐式判为 True。"""

    if raw_value is None or raw_value == "":
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是 boolean")
    return raw_value


def _build_edge_image(
    image_matrix: object,
    *,
    cv2_module: object,
    input_mode: str,
    canny_threshold1: float,
    canny_threshold2: float,
) -> object:
    """把灰度 Search ROI 转换为 HoughLinesP 所需的二值边缘图。"""

    if input_mode == "auto-canny":
        return cv2_module.Canny(image_matrix, canny_threshold1, canny_threshold2)
    _minimum, maximum, _minimum_location, _maximum_location = cv2_module.minMaxLoc(image_matrix)
    if maximum <= 0:
        return image_matrix
    return cv2_module.threshold(image_matrix, 0, 255, cv2_module.THRESH_BINARY)[1]


def _read_optional_angle_deg(raw_value: object, *, field_name: str) -> float | None:
    """读取可选角度过滤参数。"""

    if raw_value is None or raw_value == "":
        return None
    normalized_value = float(raw_value)
    if not math.isfinite(normalized_value):
        raise InvalidRequestError(f"{field_name} 必须是有效角度")
    if normalized_value < -90.0 or normalized_value > 90.0:
        raise InvalidRequestError(f"{field_name} 必须在 -90 到 90 度之间")
    return normalized_value


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


def _angle_passes_filter(angle_deg: float, *, angle_min_deg: float | None, angle_max_deg: float | None) -> bool:
    """判断线段角度是否落在可选过滤范围内。"""

    if angle_min_deg is not None and angle_deg < angle_min_deg:
        return False
    if angle_max_deg is not None and angle_deg > angle_max_deg:
        return False
    return True


def _angle_distance_deg(first_angle: float, second_angle: float) -> float:
    """计算无方向直线在 180 度周期内的最小角差。"""

    raw_distance = abs(first_angle - second_angle) % 180.0
    return min(raw_distance, 180.0 - raw_distance)


def _projection_interval(line_item: dict[str, object], *, unit_x: float, unit_y: float) -> tuple[float, float]:
    """把线段投影到指定方向并返回有序区间。"""

    start_xy = line_item["start_xy"]
    end_xy = line_item["end_xy"]
    assert isinstance(start_xy, list) and isinstance(end_xy, list)
    start_projection = float(start_xy[0]) * unit_x + float(start_xy[1]) * unit_y
    end_projection = float(end_xy[0]) * unit_x + float(end_xy[1]) * unit_y
    return min(start_projection, end_projection), max(start_projection, end_projection)


def _lines_are_duplicates(
    candidate: dict[str, object],
    existing: dict[str, object],
    *,
    angle_tolerance_deg: float,
    distance_tolerance_pixels: float,
) -> bool:
    """判断两条 Hough 线段是否描述同一条物理直线。"""

    candidate_angle = float(candidate["angle_deg"])
    if _angle_distance_deg(candidate_angle, float(existing["angle_deg"])) > angle_tolerance_deg:
        return False
    angle_radians = math.radians(candidate_angle)
    unit_x = math.cos(angle_radians)
    unit_y = math.sin(angle_radians)
    normal_x = -unit_y
    normal_y = unit_x
    candidate_midpoint = candidate["midpoint_xy"]
    existing_midpoint = existing["midpoint_xy"]
    assert isinstance(candidate_midpoint, list) and isinstance(existing_midpoint, list)
    normal_distance = abs(
        (float(candidate_midpoint[0]) - float(existing_midpoint[0])) * normal_x
        + (float(candidate_midpoint[1]) - float(existing_midpoint[1])) * normal_y
    )
    if normal_distance > distance_tolerance_pixels:
        return False
    candidate_start, candidate_end = _projection_interval(candidate, unit_x=unit_x, unit_y=unit_y)
    existing_start, existing_end = _projection_interval(existing, unit_x=unit_x, unit_y=unit_y)
    interval_gap = max(candidate_start, existing_start) - min(candidate_end, existing_end)
    return interval_gap <= distance_tolerance_pixels


def _deduplicate_lines(
    line_items: list[dict[str, object]],
    *,
    angle_tolerance_deg: float,
    distance_tolerance_pixels: float,
) -> list[dict[str, object]]:
    """按既定排序保留代表线段，并过滤同一直线的重复片段。"""

    deduplicated_items: list[dict[str, object]] = []
    for line_item in line_items:
        if any(
            _lines_are_duplicates(
                line_item,
                current_item,
                angle_tolerance_deg=angle_tolerance_deg,
                distance_tolerance_pixels=distance_tolerance_pixels,
            )
            for current_item in deduplicated_items
        ):
            continue
        deduplicated_items.append(line_item)
    for line_index, line_item in enumerate(deduplicated_items, start=1):
        line_item["line_index"] = line_index
    return deduplicated_items


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行概率 Hough 直线检测。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, source_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    image_height = int(image_matrix.shape[0])
    image_width = int(image_matrix.shape[1])
    search_roi = resolve_search_roi(request, image_matrix=image_matrix)
    search_image_matrix = search_roi.image_matrix
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
    angle_min_deg = _read_optional_angle_deg(request.parameters.get("angle_min_deg"), field_name="angle_min_deg")
    angle_max_deg = _read_optional_angle_deg(request.parameters.get("angle_max_deg"), field_name="angle_max_deg")
    if angle_min_deg is not None and angle_max_deg is not None and angle_min_deg > angle_max_deg:
        raise InvalidRequestError("angle_min_deg 不能大于 angle_max_deg")
    input_mode = _read_input_mode(request.parameters.get("input_mode"))
    canny_threshold1 = _read_canny_threshold(
        request.parameters.get("canny_threshold1"),
        field_name="canny_threshold1",
        default_value=50.0,
    )
    canny_threshold2 = _read_canny_threshold(
        request.parameters.get("canny_threshold2"),
        field_name="canny_threshold2",
        default_value=150.0,
    )
    if canny_threshold2 <= canny_threshold1:
        raise InvalidRequestError("canny_threshold2 必须大于 canny_threshold1")
    sort_by = _normalize_sort_by(request.parameters.get("sort_by"))
    descending = _read_boolean(
        request.parameters.get("descending"),
        field_name="descending",
        default_value=True,
    )
    limit = read_find_result_limit(request.parameters.get("limit"))
    deduplicate = _read_boolean(
        request.parameters.get("deduplicate"),
        field_name="deduplicate",
        default_value=True,
    )
    deduplicate_angle_tolerance_deg = _read_non_negative_float(
        request.parameters.get("deduplicate_angle_tolerance_deg"),
        field_name="deduplicate_angle_tolerance_deg",
        default_value=2.0,
    )
    if deduplicate_angle_tolerance_deg > 45.0:
        raise InvalidRequestError("deduplicate_angle_tolerance_deg 不能大于 45")
    deduplicate_distance_pixels = _read_non_negative_float(
        request.parameters.get("deduplicate_distance_pixels"),
        field_name="deduplicate_distance_pixels",
        default_value=8.0,
    )
    processing_max_long_edge = read_processing_max_long_edge(
        request.parameters.get("processing_max_long_edge")
    )
    processing_image = build_processing_image(
        search_image_matrix,
        cv2_module=cv2_module,
        max_long_edge=processing_max_long_edge,
    )
    processing_scale = min(
        float(processing_image.processing_width) / float(processing_image.source_width),
        float(processing_image.processing_height) / float(processing_image.source_height),
    )
    edge_image_matrix = _build_edge_image(
        processing_image.image_matrix,
        cv2_module=cv2_module,
        input_mode=input_mode,
        canny_threshold1=canny_threshold1,
        canny_threshold2=canny_threshold2,
    )

    raw_lines = cv2_module.HoughLinesP(
        edge_image_matrix,
        rho=rho_resolution,
        theta=math.radians(theta_step_deg),
        threshold=threshold,
        minLineLength=min_line_length * processing_scale,
        maxLineGap=max_line_gap * processing_scale,
    )
    line_items: list[dict[str, object]] = []
    if raw_lines is not None:
        for line_index, raw_line in enumerate(raw_lines, start=1):
            raw_x1, raw_y1, raw_x2, raw_y2 = [float(raw_value) for raw_value in raw_line.reshape(-1).tolist()[:4]]
            x1_value = round(raw_x1 * processing_image.scale_x_to_source + search_roi.offset_x, 4)
            x2_value = round(raw_x2 * processing_image.scale_x_to_source + search_roi.offset_x, 4)
            y1_value = round(raw_y1 * processing_image.scale_y_to_source + search_roi.offset_y, 4)
            y2_value = round(raw_y2 * processing_image.scale_y_to_source + search_roi.offset_y, 4)
            dx_pixels = float(x2_value - x1_value)
            dy_pixels = float(y2_value - y1_value)
            length_pixels = round(float(math.hypot(dx_pixels, dy_pixels)), 4)
            angle_deg = _normalize_angle_deg(dx_pixels=dx_pixels, dy_pixels=dy_pixels)
            if not _angle_passes_filter(angle_deg, angle_min_deg=angle_min_deg, angle_max_deg=angle_max_deg):
                continue
            midpoint_x = round((float(x1_value) + float(x2_value)) / 2.0, 4)
            midpoint_y = round((float(y1_value) + float(y2_value)) / 2.0, 4)
            line_items.append(
                {
                    "line_index": int(line_index),
                    "start_xy": [x1_value, y1_value],
                    "end_xy": [x2_value, y2_value],
                    "dx_pixels": round(dx_pixels, 4),
                    "dy_pixels": round(dy_pixels, 4),
                    "length_pixels": length_pixels,
                    "angle_deg": angle_deg,
                    "midpoint_xy": [midpoint_x, midpoint_y],
                    "midpoint_x": midpoint_x,
                    "midpoint_y": midpoint_y,
                    "bbox_xyxy": [
                        round(min(x1_value, x2_value), 4),
                        round(min(y1_value, y2_value), 4),
                        round(max(x1_value, x2_value), 4),
                        round(max(y1_value, y2_value), 4),
                    ],
                }
            )

    line_items.sort(key=lambda current_item: current_item[sort_by], reverse=descending)
    raw_line_count = len(line_items)
    if deduplicate:
        line_items = _deduplicate_lines(
            line_items,
            angle_tolerance_deg=deduplicate_angle_tolerance_deg,
            distance_tolerance_pixels=deduplicate_distance_pixels,
        )
    line_items = line_items[:limit]
    for line_index, line_item in enumerate(line_items, start=1):
        line_item["line_index"] = line_index

    outputs: dict[str, object] = {
        "lines": build_lines_payload(
            items=line_items,
            source_image=image_payload,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(
            {
                "count": len(line_items),
                "raw_count": raw_line_count,
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "deduplicate": deduplicate,
                "deduplicate_angle_tolerance_deg": deduplicate_angle_tolerance_deg,
                "deduplicate_distance_pixels": deduplicate_distance_pixels,
                "input_mode": input_mode,
                "canny_threshold1": canny_threshold1,
                "canny_threshold2": canny_threshold2,
                "processing_max_long_edge": processing_max_long_edge,
                "rho_resolution": rho_resolution,
                "theta_step_deg": theta_step_deg,
                "threshold": threshold,
                "min_line_length": min_line_length,
                "max_line_gap": max_line_gap,
                "angle_min_deg": angle_min_deg,
                "angle_max_deg": angle_max_deg,
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
                **build_search_roi_summary(search_roi),
                **build_processing_summary(processing_image),
            }
        ),
    }
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=image_payload,
            title="Hough Lines",
            artifact_name="hough-lines-debug-preview",
            overlays=_build_line_overlays(line_items, search_roi=search_roi),
            interaction=_build_line_interaction(
                rho_resolution=rho_resolution,
                theta_step_deg=theta_step_deg,
                threshold=threshold,
                min_line_length=min_line_length,
                max_line_gap=max_line_gap,
                angle_min_deg=angle_min_deg,
                angle_max_deg=angle_max_deg,
                input_mode=input_mode,
                canny_threshold1=canny_threshold1,
                canny_threshold2=canny_threshold2,
                processing_max_long_edge=processing_max_long_edge,
                deduplicate=deduplicate,
                deduplicate_angle_tolerance_deg=deduplicate_angle_tolerance_deg,
                deduplicate_distance_pixels=deduplicate_distance_pixels,
                image_width=image_width,
                image_height=image_height,
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
    angle_min_deg: float | None,
    angle_max_deg: float | None,
    input_mode: str,
    canny_threshold1: float,
    canny_threshold2: float,
    processing_max_long_edge: int,
    deduplicate: bool,
    deduplicate_angle_tolerance_deg: float,
    deduplicate_distance_pixels: float,
    image_width: int,
    image_height: int,
) -> dict[str, object]:
    """声明 Hough Lines 在图片面板中的取参和调参能力。"""

    long_edge, diagonal_length = _build_line_control_ranges(image_width=image_width, image_height=image_height)
    return build_debug_panel_interaction(
        tools=[
            build_interaction_tool(
                "line",
                "Direction Line",
                ["search_bbox_xyxy", "min_line_length", "angle_min_deg", "angle_max_deg"],
                extra={
                    "angle_tolerance_deg": 8.0,
                    "search_padding_ratio": 0.08,
                    "search_padding_min": 8.0,
                },
            ),
            build_interaction_tool("rect", "Search ROI", ["search_bbox_xyxy"]),
        ],
        controls=[
            build_select_control(
                "input_mode",
                "Input Mode",
                input_mode,
                options=[("auto-canny", "Auto Canny"), ("binary-edge", "Binary Edge")],
            ),
            build_numeric_control(
                "canny_threshold1",
                "Canny Threshold 1",
                canny_threshold1,
                min_value=0.0,
                max_value=255.0,
                step=1.0,
            ),
            build_numeric_control(
                "canny_threshold2",
                "Canny Threshold 2",
                canny_threshold2,
                min_value=0.0,
                max_value=255.0,
                step=1.0,
            ),
            build_numeric_control(
                "rho_resolution",
                "Rho Resolution",
                rho_resolution,
                min_value=0.1,
                max_value=10.0,
                step=0.1,
            ),
            build_numeric_control(
                "theta_step_deg",
                "Theta Step Deg",
                theta_step_deg,
                min_value=0.1,
                max_value=10.0,
                step=0.1,
            ),
            build_numeric_control("threshold", "Threshold", threshold, min_value=1.0, max_value=long_edge, step=1.0),
            build_numeric_control(
                "min_line_length",
                "Min Line Length",
                min_line_length,
                min_value=0.0,
                max_value=diagonal_length,
                step=1.0,
            ),
            build_numeric_control(
                "max_line_gap",
                "Max Line Gap",
                max_line_gap,
                min_value=0.0,
                max_value=long_edge,
                step=1.0,
            ),
            build_numeric_control(
                "angle_min_deg",
                "Angle Min Deg",
                -90.0 if angle_min_deg is None else angle_min_deg,
                min_value=-90.0,
                max_value=90.0,
                step=0.5,
            ),
            build_numeric_control(
                "angle_max_deg",
                "Angle Max Deg",
                90.0 if angle_max_deg is None else angle_max_deg,
                min_value=-90.0,
                max_value=90.0,
                step=0.5,
            ),
            build_numeric_control(
                "processing_max_long_edge",
                "Processing Max Long Edge",
                processing_max_long_edge,
                min_value=256.0,
                max_value=32768.0,
                step=256.0,
            ),
            build_checkbox_control("deduplicate", "Deduplicate", deduplicate),
            build_numeric_control(
                "deduplicate_angle_tolerance_deg",
                "Deduplicate Angle Tolerance Deg",
                deduplicate_angle_tolerance_deg,
                min_value=0.0,
                max_value=45.0,
                step=0.5,
            ),
            build_numeric_control(
                "deduplicate_distance_pixels",
                "Deduplicate Distance Pixels",
                deduplicate_distance_pixels,
                min_value=0.0,
                max_value=long_edge,
                step=1.0,
            ),
        ],
    )


def _build_line_control_ranges(*, image_width: int, image_height: int) -> tuple[float, float]:
    """按原图尺寸生成 Hough Lines 调参范围，适配 20MP/8K 工业图像。"""

    normalized_width = max(1, int(image_width))
    normalized_height = max(1, int(image_height))
    long_edge = float(max(300, normalized_width, normalized_height))
    diagonal_length = float(max(1200, math.ceil(math.hypot(normalized_width, normalized_height))))
    return long_edge, diagonal_length


def _build_line_overlays(
    line_items: list[dict[str, object]],
    *,
    search_roi: ResolvedSearchRoi,
) -> list[dict[str, object]]:
    """把 Hough 直线检测结果转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    search_roi_overlay = build_search_roi_overlay(search_roi)
    if search_roi_overlay is not None:
        overlays.append(search_roi_overlay)
    for line_item in line_items:
        start_xy = line_item.get("start_xy")
        end_xy = line_item.get("end_xy")
        if not isinstance(start_xy, list) or len(start_xy) < 2 or not isinstance(end_xy, list) or len(end_xy) < 2:
            continue
        line_index = line_item.get("line_index", len(overlays) + 1)
        overlays.append(
            build_line_overlay(
                overlay_id=f"line-{line_index}",
                label=f"line {line_index}",
                line_xyxy=[
                    float(start_xy[0]),
                    float(start_xy[1]),
                    float(end_xy[0]),
                    float(end_xy[1]),
                ],
            )
        )
    return overlays
