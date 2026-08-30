"""工业二维视觉通用直线、椭圆、矩形、边缘对和径向量测节点。"""

from __future__ import annotations

import math
from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    ExecutionControl,
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_choice,
    read_float,
    read_int,
    read_number_list,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    build_circles_payload,
    build_ellipses_payload,
    build_lines_payload,
    build_points_payload,
    require_ellipses_payload,
)

LINE_MEASURE_NODE_TYPE_ID = "custom.opencv.line-measure"
ELLIPSE_MEASURE_NODE_TYPE_ID = "custom.opencv.ellipse-measure"
RECTANGLE_MEASURE_NODE_TYPE_ID = "custom.opencv.rectangle-measure"
EDGE_PAIR_MEASURE_NODE_TYPE_ID = "custom.opencv.edge-pair-measure"
GRAY_PROFILE_MEASURE_NODE_TYPE_ID = "custom.opencv.gray-profile-measure"
RADIAL_LINE_SEARCH_NODE_TYPE_ID = "custom.opencv.radial-line-search"


def handle_gray_profile_measure(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """沿线或带状区域输出灰度剖面、梯度和峰谷位置。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    source_payload, _, gray = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    start_xy, end_xy = _read_line_parameters(request)
    sample_count = read_int(
        request.parameters.get("sample_count"),
        field_name="sample_count",
        default=max(2, int(round(_distance(start_xy, end_xy))) + 1),
        minimum=2,
        maximum=65536,
    )
    band_width = read_float(
        request.parameters.get("band_width"),
        field_name="band_width",
        default=1.0,
        minimum=1.0,
        maximum=4096.0,
    )
    profile, sample_xy = _sample_profile(
        gray,
        start_xy=start_xy,
        end_xy=end_xy,
        sample_count=sample_count,
        band_width=band_width,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    smooth_sigma = read_float(
        request.parameters.get("smooth_sigma"),
        field_name="smooth_sigma",
        default=0.0,
        minimum=0.0,
        maximum=100.0,
    )
    if smooth_sigma > 0:
        profile = cv2_module.GaussianBlur(
            profile.reshape(1, -1),
            (0, 0),
            sigmaX=smooth_sigma,
        ).reshape(-1)
    gradient = np_module.gradient(profile.astype(np_module.float64))
    peak_count = read_int(
        request.parameters.get("peak_count"),
        field_name="peak_count",
        default=5,
        minimum=1,
        maximum=128,
    )
    maxima = _rank_extrema(profile, count=peak_count, maximum=True, np_module=np_module)
    minima = _rank_extrema(profile, count=peak_count, maximum=False, np_module=np_module)
    execution_control.raise_if_cancelled_or_expired()
    payload = {
        "format_id": "amvision.gray-profile.v1",
        "source_image": source_payload,
        "coordinate_space": "source-image-pixels",
        "unit": "pixel",
        "start_xy": start_xy,
        "end_xy": end_xy,
        "band_width": band_width,
        "sample_count": sample_count,
        "distance_step": _distance(start_xy, end_xy) / (sample_count - 1),
        "sample_xy": sample_xy.round(6).tolist(),
        "values": profile.astype(float).round(8).tolist(),
        "gradient": gradient.round(8).tolist(),
        "maxima": _build_extrema_items(maxima, profile, sample_xy),
        "minima": _build_extrema_items(minima, profile, sample_xy),
    }
    return {"profile": build_value_payload(payload)}


def handle_edge_pair_measure(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """沿灰度剖面查找最强的同极性或异极性边缘对。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    source_payload, _, gray = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    start_xy, end_xy = _read_line_parameters(request)
    sample_count = read_int(
        request.parameters.get("sample_count"),
        field_name="sample_count",
        default=max(3, int(round(_distance(start_xy, end_xy))) + 1),
        minimum=3,
        maximum=65536,
    )
    profile, sample_xy = _sample_profile(
        gray,
        start_xy=start_xy,
        end_xy=end_xy,
        sample_count=sample_count,
        band_width=read_float(
            request.parameters.get("band_width"),
            field_name="band_width",
            default=3.0,
            minimum=1.0,
            maximum=4096.0,
        ),
        cv2_module=cv2_module,
        np_module=np_module,
    )
    gradient = np_module.gradient(profile.astype(np_module.float64))
    threshold = read_float(
        request.parameters.get("gradient_threshold"),
        field_name="gradient_threshold",
        default=5.0,
        minimum=0.0,
    )
    polarity = read_choice(
        request.parameters.get("pair_polarity"),
        field_name="pair_polarity",
        choices={"opposite", "same", "any"},
        default="opposite",
    )
    minimum_spacing = read_float(
        request.parameters.get("minimum_spacing"),
        field_name="minimum_spacing",
        default=1.0,
        minimum=0.0,
    )
    maximum_spacing = read_float(
        request.parameters.get("maximum_spacing"),
        field_name="maximum_spacing",
        default=_distance(start_xy, end_xy),
        minimum=0.0,
    )
    if maximum_spacing < minimum_spacing:
        raise InvalidRequestError("maximum_spacing 必须大于等于 minimum_spacing")
    pair = _select_edge_pair(
        gradient,
        sample_xy=sample_xy,
        threshold=threshold,
        polarity=polarity,
        minimum_spacing=minimum_spacing,
        maximum_spacing=maximum_spacing,
        np_module=np_module,
        execution_control=execution_control,
    )
    values: dict[str, object] = {
        "found": pair is not None,
        "pair_polarity": polarity,
        "gradient_threshold": threshold,
    }
    points_items: list[dict[str, object]] = []
    if pair is not None:
        first_index, second_index = pair
        first_xy = sample_xy[first_index]
        second_xy = sample_xy[second_index]
        spacing = float(np_module.linalg.norm(second_xy - first_xy))
        values.update(
            {
                "first_index": int(first_index),
                "second_index": int(second_index),
                "first_xy": first_xy.round(6).tolist(),
                "second_xy": second_xy.round(6).tolist(),
                "first_gradient": round(float(gradient[first_index]), 8),
                "second_gradient": round(float(gradient[second_index]), 8),
                "spacing": round(spacing, 8),
            }
        )
        for point_index, (label, xy, score) in enumerate(
            (
                ("first-edge", first_xy, abs(float(gradient[first_index]))),
                ("second-edge", second_xy, abs(float(gradient[second_index]))),
            )
        ):
            points_items.append(
                {
                    "point_id": f"edge-{point_index + 1}",
                    "point_index": point_index,
                    "xy": xy.tolist(),
                    "label": label,
                    "diagnostics": {"gradient_strength": score},
                }
            )
    return {
        "points": build_points_payload(
            items=points_items,
            coordinate_space="source-image-pixels",
            unit="pixel",
        ),
        "measurements": _measurement_payload(
            measurement_id="edge-pair-1",
            measurement_kind="edge-pair",
            values=values,
            source_image=source_payload,
        ),
    }


def handle_line_measure(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """沿名义线布置卡尺并拟合亚像素边缘直线。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    source_payload, source_key, gray = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    start_xy, end_xy = _read_line_parameters(request)
    edge_points, strengths = _measure_edge_points_along_line(
        gray,
        start_xy=start_xy,
        end_xy=end_xy,
        caliper_length=read_float(
            request.parameters.get("caliper_length"),
            field_name="caliper_length",
            default=20.0,
            minimum=2.0,
            maximum=8192.0,
        ),
        caliper_count=read_int(
            request.parameters.get("caliper_count"),
            field_name="caliper_count",
            default=20,
            minimum=2,
            maximum=4096,
        ),
        threshold=read_float(
            request.parameters.get("gradient_threshold"),
            field_name="gradient_threshold",
            default=5.0,
            minimum=0.0,
        ),
        polarity=read_choice(
            request.parameters.get("edge_polarity"),
            field_name="edge_polarity",
            choices={"any", "dark-to-bright", "bright-to-dark"},
            default="any",
        ),
        cv2_module=cv2_module,
        np_module=np_module,
        execution_control=execution_control,
    )
    if len(edge_points) < 2:
        raise InvalidRequestError(
            "line-measure 有效边缘点不足",
            details={"valid_count": len(edge_points)},
        )
    fitted_start, fitted_end, residuals = _fit_line_segment(
        edge_points,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    angle = math.degrees(
        math.atan2(fitted_end[1] - fitted_start[1], fitted_end[0] - fitted_start[0])
    )
    line_item = {
        "line_index": 1,
        "start_xy": fitted_start,
        "end_xy": fitted_end,
        "length_pixels": _distance(fitted_start, fitted_end),
        "angle_deg": angle,
        "residual_rms": float(np_module.sqrt(np_module.mean(residuals**2))),
        "residual_max": float(np_module.max(residuals)),
        "valid_caliper_count": len(edge_points),
    }
    point_items = [
        {
            "point_id": f"line-edge-{index + 1}",
            "point_index": index,
            "xy": point.tolist(),
            "diagnostics": {"edge_strength": float(strengths[index])},
        }
        for index, point in enumerate(edge_points)
    ]
    values = {
        "valid_count": len(edge_points),
        "requested_count": read_int(
            request.parameters.get("caliper_count"),
            field_name="caliper_count",
            default=20,
            minimum=2,
            maximum=4096,
        ),
        "valid_ratio": len(edge_points)
        / read_int(
            request.parameters.get("caliper_count"),
            field_name="caliper_count",
            default=20,
            minimum=2,
            maximum=4096,
        ),
        "residual_rms": line_item["residual_rms"],
        "residual_max": line_item["residual_max"],
        "angle_degrees": angle,
    }
    return {
        "points": build_points_payload(
            items=point_items,
            coordinate_space="source-image-pixels",
            unit="pixel",
        ),
        "lines": build_lines_payload(
            items=[line_item],
            source_image=source_payload,
            source_object_key=source_key,
        ),
        "measurements": _measurement_payload(
            measurement_id="line-measure-1",
            measurement_kind="line-fit",
            values=values,
            source_image=source_payload,
        ),
    }


def handle_radial_line_search(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """沿多条径向搜索边缘并可拟合圆或椭圆。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    source_payload, source_key, gray = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    center = read_number_list(
        request.parameters.get("center_xy"),
        field_name="center_xy",
        exact_length=2,
    )
    inner_radius = read_float(
        request.parameters.get("inner_radius"),
        field_name="inner_radius",
        default=0.0,
        minimum=0.0,
    )
    outer_radius = read_float(
        request.parameters.get("outer_radius"),
        field_name="outer_radius",
        default=100.0,
        minimum=0.0,
    )
    if outer_radius <= inner_radius:
        raise InvalidRequestError("outer_radius 必须大于 inner_radius")
    ray_count = read_int(
        request.parameters.get("ray_count"),
        field_name="ray_count",
        default=72,
        minimum=5,
        maximum=4096,
    )
    threshold = read_float(
        request.parameters.get("gradient_threshold"),
        field_name="gradient_threshold",
        default=5.0,
        minimum=0.0,
    )
    polarity = read_choice(
        request.parameters.get("edge_polarity"),
        field_name="edge_polarity",
        choices={"any", "dark-to-bright", "bright-to-dark"},
        default="any",
    )
    angles = np_module.linspace(0.0, 2.0 * math.pi, ray_count, endpoint=False)
    points: list[list[float]] = []
    strengths: list[float] = []
    for angle in angles:
        execution_control.raise_if_cancelled_or_expired()
        direction = [math.cos(float(angle)), math.sin(float(angle))]
        start = [
            center[0] + inner_radius * direction[0],
            center[1] + inner_radius * direction[1],
        ]
        end = [
            center[0] + outer_radius * direction[0],
            center[1] + outer_radius * direction[1],
        ]
        profile, coordinates = _sample_profile(
            gray,
            start_xy=start,
            end_xy=end,
            sample_count=max(3, int(math.ceil(outer_radius - inner_radius)) + 1),
            band_width=1.0,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        edge = _select_edge(profile, polarity=polarity, threshold=threshold, np_module=np_module)
        if edge is not None:
            edge_index, strength = edge
            points.append(coordinates[edge_index].tolist())
            strengths.append(strength)
    point_items = [
        {
            "point_id": f"radial-edge-{index + 1}",
            "point_index": index,
            "xy": point,
            "diagnostics": {"edge_strength": strengths[index]},
        }
        for index, point in enumerate(points)
    ]
    fit_kind = read_choice(
        request.parameters.get("fit_kind"),
        field_name="fit_kind",
        choices={"none", "circle", "ellipse"},
        default="circle",
    )
    outputs: dict[str, object] = {
        "points": build_points_payload(
            items=point_items,
            coordinate_space="source-image-pixels",
            unit="pixel",
        )
    }
    values: dict[str, object] = {
        "found_count": len(points),
        "ray_count": ray_count,
        "coverage_ratio": len(points) / ray_count,
        "fit_kind": fit_kind,
    }
    if fit_kind == "circle" and len(points) >= 3:
        fitted_center, radius, residuals = _fit_circle(points, np_module=np_module)
        circle_item = {
            "circle_index": 1,
            "center_xy": fitted_center,
            "radius": radius,
            "diameter": radius * 2.0,
            "area": math.pi * radius * radius,
            "residual_rms": float(np_module.sqrt(np_module.mean(residuals**2))),
        }
        outputs["circles"] = build_circles_payload(
            items=[circle_item],
            source_image=source_payload,
            source_object_key=source_key,
        )
        values.update(circle_item)
    elif fit_kind == "ellipse" and len(points) >= 5:
        ellipse_item, residuals = _fit_ellipse(points, cv2_module=cv2_module, np_module=np_module)
        outputs["ellipses"] = build_ellipses_payload(
            items=[ellipse_item],
            coordinate_space="source-image-pixels",
            unit="pixel",
            source_image=source_payload,
            source_object_key=source_key,
        )
        values.update(
            {
                **ellipse_item,
                "residual_rms": float(np_module.sqrt(np_module.mean(residuals**2))),
            }
        )
    outputs["measurements"] = _measurement_payload(
        measurement_id="radial-search-1",
        measurement_kind="radial-edge-search",
        values=values,
        source_image=source_payload,
    )
    return outputs


def handle_ellipse_measure(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """沿名义椭圆法向搜索边缘并重新拟合椭圆。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    source_payload, source_key, gray = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    nominal = require_ellipses_payload(request.input_values.get("ellipse"))
    if len(nominal["items"]) != 1:
        raise InvalidRequestError("ellipse-measure 要求 ellipse 恰好包含一个项目")
    item = nominal["items"][0]
    sample_count = read_int(
        request.parameters.get("sample_count"),
        field_name="sample_count",
        default=72,
        minimum=5,
        maximum=4096,
    )
    search_length = read_float(
        request.parameters.get("search_length"),
        field_name="search_length",
        default=20.0,
        minimum=2.0,
        maximum=8192.0,
    )
    threshold = read_float(
        request.parameters.get("gradient_threshold"),
        field_name="gradient_threshold",
        default=5.0,
        minimum=0.0,
    )
    points, strengths = _measure_ellipse_points(
        gray,
        ellipse=item,
        sample_count=sample_count,
        search_length=search_length,
        threshold=threshold,
        polarity=read_choice(
            request.parameters.get("edge_polarity"),
            field_name="edge_polarity",
            choices={"any", "dark-to-bright", "bright-to-dark"},
            default="any",
        ),
        cv2_module=cv2_module,
        np_module=np_module,
        execution_control=execution_control,
    )
    if len(points) < 5:
        raise InvalidRequestError(
            "ellipse-measure 有效边缘点不足",
            details={"valid_count": len(points)},
        )
    fitted, residuals = _fit_ellipse(points, cv2_module=cv2_module, np_module=np_module)
    fitted["valid_sample_count"] = len(points)
    fitted["coverage_ratio"] = len(points) / sample_count
    fitted["residual_rms"] = float(np_module.sqrt(np_module.mean(residuals**2)))
    point_items = [
        {
            "point_id": f"ellipse-edge-{index + 1}",
            "point_index": index,
            "xy": point,
            "diagnostics": {"edge_strength": strengths[index]},
        }
        for index, point in enumerate(points)
    ]
    return {
        "points": build_points_payload(
            items=point_items,
            coordinate_space=str(nominal["coordinate_space"]),
            unit=str(nominal["unit"]),
        ),
        "ellipses": build_ellipses_payload(
            items=[fitted],
            coordinate_space=str(nominal["coordinate_space"]),
            unit=str(nominal["unit"]),
            source_image=source_payload,
            source_object_key=source_key,
        ),
        "measurements": _measurement_payload(
            measurement_id="ellipse-measure-1",
            measurement_kind="ellipse-fit",
            values={
                "valid_sample_count": len(points),
                "sample_count": sample_count,
                "coverage_ratio": len(points) / sample_count,
                "residual_rms": fitted["residual_rms"],
                "major_axis": fitted["major_axis"],
                "minor_axis": fitted["minor_axis"],
                "angle_degrees": fitted["angle_deg"],
            },
            source_image=source_payload,
            coordinate_space=str(nominal["coordinate_space"]),
            unit=str(nominal["unit"]),
        ),
    }


def handle_rectangle_measure(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """沿名义旋转矩形四边量测并输出宽高、角度和平行度。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    source_payload, source_key, gray = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    center = read_number_list(
        request.parameters.get("center_xy"),
        field_name="center_xy",
        exact_length=2,
    )
    width = read_float(
        request.parameters.get("width"),
        field_name="width",
        default=100.0,
        minimum=1.0,
    )
    height = read_float(
        request.parameters.get("height"),
        field_name="height",
        default=100.0,
        minimum=1.0,
    )
    angle = read_float(
        request.parameters.get("angle_degrees"),
        field_name="angle_degrees",
        default=0.0,
    )
    box = cv2_module.boxPoints(((center[0], center[1]), (width, height), angle))
    fitted_lines: list[tuple[list[float], list[float]]] = []
    all_points: list[list[float]] = []
    for side_index in range(4):
        execution_control.raise_if_cancelled_or_expired()
        start = box[side_index].tolist()
        end = box[(side_index + 1) % 4].tolist()
        edge_points, _ = _measure_edge_points_along_line(
            gray,
            start_xy=start,
            end_xy=end,
            caliper_length=read_float(
                request.parameters.get("caliper_length"),
                field_name="caliper_length",
                default=20.0,
                minimum=2.0,
            ),
            caliper_count=read_int(
                request.parameters.get("calipers_per_side"),
                field_name="calipers_per_side",
                default=12,
                minimum=2,
                maximum=1024,
            ),
            threshold=read_float(
                request.parameters.get("gradient_threshold"),
                field_name="gradient_threshold",
                default=5.0,
                minimum=0.0,
            ),
            polarity="any",
            cv2_module=cv2_module,
            np_module=np_module,
            execution_control=execution_control,
        )
        if len(edge_points) < 2:
            raise InvalidRequestError(
                "rectangle-measure 某一边有效点不足",
                details={"side_index": side_index, "valid_count": len(edge_points)},
            )
        fitted_start, fitted_end, _ = _fit_line_segment(
            edge_points,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        fitted_lines.append((fitted_start, fitted_end))
        all_points.extend(point.tolist() for point in edge_points)
    corners = [
        _line_intersection(fitted_lines[index - 1], fitted_lines[index], np_module=np_module)
        for index in range(4)
    ]
    side_lengths = [
        _distance(corners[index], corners[(index + 1) % 4]) for index in range(4)
    ]
    side_angles = [
        _line_angle(line[0], line[1]) for line in fitted_lines
    ]
    width_measured = (side_lengths[0] + side_lengths[2]) / 2.0
    height_measured = (side_lengths[1] + side_lengths[3]) / 2.0
    parallelism = max(
        _parallel_angle_error(side_angles[0], side_angles[2]),
        _parallel_angle_error(side_angles[1], side_angles[3]),
    )
    perpendicularity = max(
        abs(90.0 - _acute_angle_difference(side_angles[index], side_angles[(index + 1) % 4]))
        for index in range(4)
    )
    line_items = [
        {
            "line_index": index + 1,
            "start_xy": line[0],
            "end_xy": line[1],
            "length_pixels": _distance(line[0], line[1]),
            "angle_deg": side_angles[index],
        }
        for index, line in enumerate(fitted_lines)
    ]
    values = {
        "center_xy": [
            sum(point[0] for point in corners) / 4.0,
            sum(point[1] for point in corners) / 4.0,
        ],
        "corners_xy": corners,
        "width": width_measured,
        "height": height_measured,
        "angle_degrees": side_angles[0],
        "parallelism_error_degrees": parallelism,
        "perpendicularity_error_degrees": perpendicularity,
        "rectangularity_error_degrees": max(parallelism, perpendicularity),
        "edge_point_count": len(all_points),
    }
    return {
        "lines": build_lines_payload(
            items=line_items,
            source_image=source_payload,
            source_object_key=source_key,
        ),
        "measurements": _measurement_payload(
            measurement_id="rectangle-measure-1",
            measurement_kind="rectangle",
            values=values,
            source_image=source_payload,
        ),
    }


def _read_line_parameters(
    request: WorkflowNodeExecutionRequest,
) -> tuple[list[float], list[float]]:
    """读取不退化的起止点。"""

    start = read_number_list(
        request.parameters.get("start_xy"),
        field_name="start_xy",
        exact_length=2,
    )
    end = read_number_list(
        request.parameters.get("end_xy"),
        field_name="end_xy",
        exact_length=2,
    )
    if _distance(start, end) <= 1e-9:
        raise InvalidRequestError("start_xy 与 end_xy 不能相同")
    return start, end


def _sample_profile(
    image: Any,
    *,
    start_xy: list[float],
    end_xy: list[float],
    sample_count: int,
    band_width: float,
    cv2_module: Any,
    np_module: Any,
) -> tuple[Any, Any]:
    """使用 remap 在任意方向按亚像素坐标采样带状灰度剖面。"""

    direction = np_module.asarray(end_xy, dtype=np_module.float64) - np_module.asarray(
        start_xy,
        dtype=np_module.float64,
    )
    direction /= np_module.linalg.norm(direction)
    normal = np_module.asarray([-direction[1], direction[0]], dtype=np_module.float64)
    along = np_module.linspace(0.0, 1.0, sample_count)
    center_xy = (
        np_module.asarray(start_xy, dtype=np_module.float64)[None, :]
        + along[:, None]
        * (
            np_module.asarray(end_xy, dtype=np_module.float64)
            - np_module.asarray(start_xy, dtype=np_module.float64)
        )[None, :]
    )
    cross_count = max(1, int(math.ceil(band_width)))
    cross = np_module.linspace(
        -(band_width - 1.0) / 2.0,
        (band_width - 1.0) / 2.0,
        cross_count,
    )
    sample_xy = center_xy[:, None, :] + cross[None, :, None] * normal[None, None, :]
    sampled = cv2_module.remap(
        image,
        sample_xy[..., 0].astype(np_module.float32),
        sample_xy[..., 1].astype(np_module.float32),
        interpolation=cv2_module.INTER_LINEAR,
        borderMode=cv2_module.BORDER_REPLICATE,
    )
    return sampled.astype(np_module.float64).mean(axis=1), center_xy


def _select_edge(
    profile: Any,
    *,
    polarity: str,
    threshold: float,
    np_module: Any,
) -> tuple[int, float] | None:
    """从单条剖面选择满足极性的最强梯度。"""

    gradient = np_module.gradient(profile.astype(np_module.float64))
    score = {
        "any": np_module.abs(gradient),
        "dark-to-bright": gradient,
        "bright-to-dark": -gradient,
    }[polarity]
    index = int(np_module.argmax(score))
    strength = float(score[index])
    if strength < threshold:
        return None
    return index, strength


def _measure_edge_points_along_line(
    image: Any,
    *,
    start_xy: list[float],
    end_xy: list[float],
    caliper_length: float,
    caliper_count: int,
    threshold: float,
    polarity: str,
    cv2_module: Any,
    np_module: Any,
    execution_control: ExecutionControl,
) -> tuple[list[Any], list[float]]:
    """沿名义线均匀布置法向卡尺并返回边缘点。"""

    start = np_module.asarray(start_xy, dtype=np_module.float64)
    end = np_module.asarray(end_xy, dtype=np_module.float64)
    direction = end - start
    direction /= np_module.linalg.norm(direction)
    normal = np_module.asarray([-direction[1], direction[0]], dtype=np_module.float64)
    centers = start[None, :] + np_module.linspace(0.0, 1.0, caliper_count)[:, None] * (
        end - start
    )[None, :]
    points: list[Any] = []
    strengths: list[float] = []
    for center in centers:
        execution_control.raise_if_cancelled_or_expired()
        scan_start = center - normal * (caliper_length / 2.0)
        scan_end = center + normal * (caliper_length / 2.0)
        profile, coordinates = _sample_profile(
            image,
            start_xy=scan_start.tolist(),
            end_xy=scan_end.tolist(),
            sample_count=max(3, int(math.ceil(caliper_length)) + 1),
            band_width=1.0,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        selected = _select_edge(
            profile,
            polarity=polarity,
            threshold=threshold,
            np_module=np_module,
        )
        if selected is None:
            continue
        index, strength = selected
        points.append(coordinates[index])
        strengths.append(strength)
    return points, strengths


def _fit_line_segment(
    points: list[Any],
    *,
    cv2_module: Any,
    np_module: Any,
) -> tuple[list[float], list[float], Any]:
    """拟合直线并以输入点投影范围生成有限线段。"""

    array = np_module.asarray(points, dtype=np_module.float32)
    vx, vy, x0, y0 = [
        float(value)
        for value in cv2_module.fitLine(
            array,
            cv2_module.DIST_L2,
            0,
            0.01,
            0.01,
        ).reshape(-1)
    ]
    direction = np_module.asarray([vx, vy], dtype=np_module.float64)
    origin = np_module.asarray([x0, y0], dtype=np_module.float64)
    projection = (array.astype(np_module.float64) - origin) @ direction
    fitted_start = origin + direction * float(projection.min())
    fitted_end = origin + direction * float(projection.max())
    normal = np_module.asarray([-direction[1], direction[0]], dtype=np_module.float64)
    residuals = np_module.abs((array.astype(np_module.float64) - origin) @ normal)
    return fitted_start.tolist(), fitted_end.tolist(), residuals


def _measure_ellipse_points(
    image: Any,
    *,
    ellipse: dict[str, object],
    sample_count: int,
    search_length: float,
    threshold: float,
    polarity: str,
    cv2_module: Any,
    np_module: Any,
    execution_control: ExecutionControl,
) -> tuple[list[list[float]], list[float]]:
    """沿名义椭圆法向采样边缘点。"""

    center = np_module.asarray(ellipse["center_xy"], dtype=np_module.float64)
    semi_major = float(ellipse["major_axis"]) / 2.0
    semi_minor = float(ellipse["minor_axis"]) / 2.0
    angle = math.radians(float(ellipse["angle_deg"]))
    rotation = np_module.asarray(
        [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]],
        dtype=np_module.float64,
    )
    points: list[list[float]] = []
    strengths: list[float] = []
    for parameter in np_module.linspace(0.0, 2.0 * math.pi, sample_count, endpoint=False):
        execution_control.raise_if_cancelled_or_expired()
        local = np_module.asarray(
            [semi_major * math.cos(parameter), semi_minor * math.sin(parameter)],
            dtype=np_module.float64,
        )
        local_normal = np_module.asarray(
            [math.cos(parameter) / semi_major, math.sin(parameter) / semi_minor],
            dtype=np_module.float64,
        )
        local_normal /= np_module.linalg.norm(local_normal)
        nominal = center + rotation @ local
        normal = rotation @ local_normal
        scan_start = nominal - normal * (search_length / 2.0)
        scan_end = nominal + normal * (search_length / 2.0)
        profile, coordinates = _sample_profile(
            image,
            start_xy=scan_start.tolist(),
            end_xy=scan_end.tolist(),
            sample_count=max(3, int(math.ceil(search_length)) + 1),
            band_width=1.0,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        selected = _select_edge(
            profile,
            polarity=polarity,
            threshold=threshold,
            np_module=np_module,
        )
        if selected is not None:
            index, strength = selected
            points.append(coordinates[index].tolist())
            strengths.append(strength)
    return points, strengths


def _fit_circle(points: list[list[float]], *, np_module: Any) -> tuple[list[float], float, Any]:
    """使用线性最小二乘拟合圆并返回径向残差。"""

    array = np_module.asarray(points, dtype=np_module.float64)
    design = np_module.column_stack((2.0 * array[:, 0], 2.0 * array[:, 1], np_module.ones(len(array))))
    target = array[:, 0] ** 2 + array[:, 1] ** 2
    solution, _, rank, _ = np_module.linalg.lstsq(design, target, rcond=None)
    if int(rank) < 3:
        raise InvalidRequestError("圆拟合点集退化")
    center = solution[:2]
    radius_squared = float(solution[2] + center @ center)
    if radius_squared <= 0:
        raise InvalidRequestError("圆拟合得到无效半径")
    radius = math.sqrt(radius_squared)
    residuals = np_module.abs(np_module.linalg.norm(array - center, axis=1) - radius)
    return center.tolist(), radius, residuals


def _fit_ellipse(
    points: list[list[float]],
    *,
    cv2_module: Any,
    np_module: Any,
) -> tuple[dict[str, object], Any]:
    """使用 OpenCV 拟合椭圆并计算近似径向残差。"""

    array = np_module.asarray(points, dtype=np_module.float32)
    (center_x, center_y), (axis_a, axis_b), angle = cv2_module.fitEllipse(array)
    major = max(float(axis_a), float(axis_b))
    minor = min(float(axis_a), float(axis_b))
    normalized_angle = float(angle + (90.0 if axis_a < axis_b else 0.0)) % 180.0
    rotation = math.radians(normalized_angle)
    centered = array.astype(np_module.float64) - np_module.asarray([center_x, center_y])
    local_x = centered[:, 0] * math.cos(rotation) + centered[:, 1] * math.sin(rotation)
    local_y = -centered[:, 0] * math.sin(rotation) + centered[:, 1] * math.cos(rotation)
    radial = np_module.sqrt((local_x / (major / 2.0)) ** 2 + (local_y / (minor / 2.0)) ** 2)
    residuals = np_module.abs(radial - 1.0) * ((major + minor) / 4.0)
    return (
        {
            "ellipse_index": 1,
            "center_xy": [float(center_x), float(center_y)],
            "major_axis": major,
            "minor_axis": minor,
            "angle_deg": normalized_angle,
        },
        residuals,
    )


def _select_edge_pair(
    gradient: Any,
    *,
    sample_xy: Any,
    threshold: float,
    polarity: str,
    minimum_spacing: float,
    maximum_spacing: float,
    np_module: Any,
    execution_control: ExecutionControl,
) -> tuple[int, int] | None:
    """按强度乘积选择满足间距和极性规则的边缘对。"""

    candidates = [
        int(index)
        for index in np_module.where(np_module.abs(gradient) >= threshold)[0].tolist()
    ]
    best: tuple[float, int, int] | None = None
    for offset, first in enumerate(candidates):
        execution_control.raise_if_cancelled_or_expired()
        for second in candidates[offset + 1 :]:
            spacing = float(np_module.linalg.norm(sample_xy[second] - sample_xy[first]))
            if spacing < minimum_spacing or spacing > maximum_spacing:
                continue
            same_sign = float(gradient[first]) * float(gradient[second]) > 0
            if polarity == "same" and not same_sign:
                continue
            if polarity == "opposite" and same_sign:
                continue
            score = abs(float(gradient[first]) * float(gradient[second]))
            if best is None or score > best[0]:
                best = (score, first, second)
    return None if best is None else (best[1], best[2])


def _rank_extrema(values: Any, *, count: int, maximum: bool, np_module: Any) -> list[int]:
    """返回局部峰或谷的稳定强度排序索引。"""

    if len(values) < 3:
        return []
    candidate = []
    for index in range(1, len(values) - 1):
        if maximum and values[index] >= values[index - 1] and values[index] >= values[index + 1]:
            candidate.append(index)
        elif not maximum and values[index] <= values[index - 1] and values[index] <= values[index + 1]:
            candidate.append(index)
    return sorted(candidate, key=lambda index: float(values[index]), reverse=maximum)[:count]


def _build_extrema_items(indices: list[int], values: Any, sample_xy: Any) -> list[dict[str, object]]:
    """构建峰谷 JSON 项。"""

    return [
        {
            "sample_index": int(index),
            "xy": sample_xy[index].round(6).tolist(),
            "value": round(float(values[index]), 8),
        }
        for index in indices
    ]


def _measurement_payload(
    *,
    measurement_id: str,
    measurement_kind: str,
    values: dict[str, object],
    source_image: dict[str, object],
    coordinate_space: str = "source-image-pixels",
    unit: str = "pixel",
) -> dict[str, object]:
    """构建通用关系/量测 measurements.v1。"""

    return {
        "coordinate_space": coordinate_space,
        "unit": unit,
        "source_image": source_image,
        "items": [
            {
                "measurement_id": measurement_id,
                "measurement_kind": measurement_kind,
                "coordinate_space": coordinate_space,
                "unit": unit,
                "values": values,
            }
        ],
        "summary": {"measurement_kind": measurement_kind, "count": 1},
    }


def _distance(first: list[float], second: list[float]) -> float:
    """返回两点欧氏距离。"""

    return math.hypot(float(second[0]) - float(first[0]), float(second[1]) - float(first[1]))


def _line_intersection(
    first: tuple[list[float], list[float]],
    second: tuple[list[float], list[float]],
    *,
    np_module: Any,
) -> list[float]:
    """计算两条无限直线交点。"""

    first_start = np_module.asarray(first[0], dtype=np_module.float64)
    first_direction = np_module.asarray(first[1], dtype=np_module.float64) - first_start
    second_start = np_module.asarray(second[0], dtype=np_module.float64)
    second_direction = np_module.asarray(second[1], dtype=np_module.float64) - second_start
    system = np_module.column_stack((first_direction, -second_direction))
    determinant = float(np_module.linalg.det(system))
    if abs(determinant) <= 1e-9:
        raise InvalidRequestError("rectangle-measure 拟合边相互平行，无法求角点")
    parameters = np_module.linalg.solve(system, second_start - first_start)
    return (first_start + parameters[0] * first_direction).tolist()


def _line_angle(start: list[float], end: list[float]) -> float:
    """返回线方向角，范围为 [0,180)。"""

    return math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 180.0


def _acute_angle_difference(first: float, second: float) -> float:
    """返回两条无向直线的锐角夹角。"""

    difference = abs(first - second) % 180.0
    return min(difference, 180.0 - difference)


def _parallel_angle_error(first: float, second: float) -> float:
    """返回两条名义平行线的角度误差。"""

    return _acute_angle_difference(first, second)


INDUSTRIAL_MEASUREMENT_NODE_HANDLERS = (
    (LINE_MEASURE_NODE_TYPE_ID, handle_line_measure),
    (ELLIPSE_MEASURE_NODE_TYPE_ID, handle_ellipse_measure),
    (RECTANGLE_MEASURE_NODE_TYPE_ID, handle_rectangle_measure),
    (EDGE_PAIR_MEASURE_NODE_TYPE_ID, handle_edge_pair_measure),
    (GRAY_PROFILE_MEASURE_NODE_TYPE_ID, handle_gray_profile_measure),
    (RADIAL_LINE_SEARCH_NODE_TYPE_ID, handle_radial_line_search),
)


__all__ = ["INDUSTRIAL_MEASUREMENT_NODE_HANDLERS"]
