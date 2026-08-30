"""工业二维几何创建、选择、变换和关系节点。"""

from __future__ import annotations

import math
from typing import Any, Callable

from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    build_circles_payload,
    build_ellipses_payload,
    build_lines_payload,
    build_points_payload,
    require_circles_payload,
    require_ellipses_payload,
    require_lines_payload,
    require_points_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.points import (
    require_coordinate_space,
    require_point_unit,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.transforms import (
    build_planar_transform_payload,
    require_planar_transform_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import require_number


POINT_CREATE_NODE_TYPE_ID = "custom.opencv.point-create"
LINE_CREATE_NODE_TYPE_ID = "custom.opencv.line-create"
CIRCLE_CREATE_NODE_TYPE_ID = "custom.opencv.circle-create"
ELLIPSE_CREATE_NODE_TYPE_ID = "custom.opencv.ellipse-create"
POINTS_SELECT_NODE_TYPE_ID = "custom.opencv.points-select"
LINES_SELECT_NODE_TYPE_ID = "custom.opencv.lines-select"
CIRCLES_SELECT_NODE_TYPE_ID = "custom.opencv.circles-select"
ELLIPSES_SELECT_NODE_TYPE_ID = "custom.opencv.ellipses-select"
TRANSFORM_CREATE_NODE_TYPE_ID = "custom.opencv.transform-2d-create"
TRANSFORM_COMPOSE_NODE_TYPE_ID = "custom.opencv.transform-2d-compose"
TRANSFORM_INVERT_NODE_TYPE_ID = "custom.opencv.transform-2d-invert"
TRANSFORM_POINTS_NODE_TYPE_ID = "custom.opencv.transform-points"
PIXEL_TO_WORLD_NODE_TYPE_ID = "custom.opencv.pixel-to-world"
WORLD_TO_PIXEL_NODE_TYPE_ID = "custom.opencv.world-to-pixel"
LINE_LINE_RELATION_NODE_TYPE_ID = "custom.opencv.line-line-relation"
POINT_CIRCLE_RELATION_NODE_TYPE_ID = "custom.opencv.point-circle-relation"
LINE_CIRCLE_RELATION_NODE_TYPE_ID = "custom.opencv.line-circle-relation"
CIRCLE_CIRCLE_RELATION_NODE_TYPE_ID = "custom.opencv.circle-circle-relation"


def handle_point_create(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从显式坐标数组创建 points.v1。"""

    raw_points = _read_input_value_or_parameter(request, "points")
    if not isinstance(raw_points, list):
        raise InvalidRequestError("Point Create 的 points 必须是数组")
    coordinate_space, unit = _read_geometry_context(request)
    items: list[dict[str, object]] = []
    for point_offset, raw_point in enumerate(raw_points):
        if isinstance(raw_point, dict):
            xy = _require_xy(raw_point.get("xy"), field_name=f"points[{point_offset}].xy")
            point_id = raw_point.get("point_id", f"point-{point_offset + 1}")
            label = raw_point.get("label")
        else:
            xy = _require_xy(raw_point, field_name=f"points[{point_offset}]")
            point_id = f"point-{point_offset + 1}"
            label = None
        item: dict[str, object] = {
            "point_id": str(point_id),
            "point_index": point_offset,
            "xy": list(xy),
        }
        if label is not None:
            item["label"] = str(label)
        items.append(item)
    return {
        "points": build_points_payload(
            items=items,
            coordinate_space=coordinate_space,
            unit=unit,
        ),
        "summary": build_value_payload({"count": len(items)}),
    }


def handle_line_create(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """由两个显式端点创建一条 lines.v1 线段。"""

    points_payload = request.input_values.get("points")
    if points_payload is not None:
        normalized_points = require_points_payload(points_payload)
        coordinate_space = str(normalized_points["coordinate_space"])
        unit = str(normalized_points["unit"])
        if request.parameters.get("coordinate_space") is not None:
            _require_context_matches(
                coordinate_space=require_coordinate_space(
                    request.parameters.get("coordinate_space")
                ),
                unit=require_point_unit(request.parameters.get("unit", unit)),
                payload=normalized_points,
            )
        if len(normalized_points["items"]) != 2:
            raise InvalidRequestError("Line Create 的 points 输入必须恰好包含两个点")
        start_xy = tuple(normalized_points["items"][0]["xy"])
        end_xy = tuple(normalized_points["items"][1]["xy"])
    else:
        coordinate_space, unit = _read_geometry_context(request)
        start_xy = _require_xy(request.parameters.get("start_xy"), field_name="start_xy")
        end_xy = _require_xy(request.parameters.get("end_xy"), field_name="end_xy")
    item = _build_line_item(start_xy=start_xy, end_xy=end_xy, line_index=1)
    return {
        "lines": build_lines_payload(
            items=[item],
            source_image=None,
            source_object_key=None,
            coordinate_space=coordinate_space,
            unit=unit,
        ),
        "summary": build_value_payload(item),
    }


def handle_circle_create(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """由中心和半径创建一条 circles.v1 记录。"""

    coordinate_space, unit = _read_geometry_context(request)
    center_xy = _require_xy(request.parameters.get("center_xy"), field_name="center_xy")
    radius = _require_positive_number(request.parameters.get("radius"), field_name="radius")
    item = _build_circle_item(center_xy=center_xy, radius=radius, circle_index=1)
    return {
        "circles": build_circles_payload(
            items=[item],
            source_image=None,
            source_object_key=None,
            coordinate_space=coordinate_space,
            unit=unit,
        ),
        "summary": build_value_payload(item),
    }


def handle_ellipse_create(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """由中心、长短轴和角度创建 ellipses.v1。"""

    coordinate_space, unit = _read_geometry_context(request)
    center_xy = _require_xy(request.parameters.get("center_xy"), field_name="center_xy")
    major_axis = _require_positive_number(
        request.parameters.get("major_axis"), field_name="major_axis"
    )
    minor_axis = _require_positive_number(
        request.parameters.get("minor_axis"), field_name="minor_axis"
    )
    if major_axis < minor_axis:
        raise InvalidRequestError("Ellipse Create 要求 major_axis 不能小于 minor_axis")
    angle_deg = require_number(request.parameters.get("angle_deg", 0.0), field_name="angle_deg")
    bbox_xyxy = _ellipse_axis_aligned_bbox(
        center_xy=center_xy,
        major_axis=major_axis,
        minor_axis=minor_axis,
        angle_deg=angle_deg,
    )
    item = {
        "ellipse_index": 1,
        "center_xy": list(center_xy),
        "major_axis": major_axis,
        "minor_axis": minor_axis,
        "size_wh": [major_axis, minor_axis],
        "angle_deg": angle_deg,
        "bbox_xyxy": bbox_xyxy,
        "area": math.pi * major_axis * minor_axis / 4.0,
    }
    return {
        "ellipses": build_ellipses_payload(
            items=[item],
            coordinate_space=coordinate_space,
            unit=unit,
        ),
        "summary": build_value_payload(item),
    }


def handle_points_select(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按一基位置和可选数值过滤选择 points.v1。"""

    payload = require_points_payload(request.input_values.get("points"))
    selected = _select_items(payload["items"], request=request)
    normalized_items = [
        {**item, "point_index": index}
        for index, item in enumerate(selected)
    ]
    return {
        "points": build_points_payload(
            items=normalized_items,
            coordinate_space=str(payload["coordinate_space"]),
            unit=str(payload["unit"]),
        ),
        "summary": _selection_summary(payload, normalized_items),
    }


def handle_lines_select(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按一基位置和可选数值过滤选择 lines.v1。"""

    payload = require_lines_payload(request.input_values.get("lines"))
    selected = _select_items(payload["items"], request=request)
    normalized_items = [
        {**item, "line_index": index}
        for index, item in enumerate(selected, start=1)
    ]
    return {
        "lines": build_lines_payload(
            items=normalized_items,
            source_image=payload.get("source_image"),
            source_object_key=_optional_text(payload.get("source_object_key")),
            coordinate_space=str(payload["coordinate_space"]),
            unit=str(payload["unit"]),
        ),
        "summary": _selection_summary(payload, normalized_items),
    }


def handle_circles_select(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按一基位置和可选数值过滤选择 circles.v1。"""

    payload = require_circles_payload(request.input_values.get("circles"))
    selected = _select_items(payload["items"], request=request)
    normalized_items = [
        {**item, "circle_index": index}
        for index, item in enumerate(selected, start=1)
    ]
    return {
        "circles": build_circles_payload(
            items=normalized_items,
            source_image=payload.get("source_image"),
            source_object_key=_optional_text(payload.get("source_object_key")),
            coordinate_space=str(payload["coordinate_space"]),
            unit=str(payload["unit"]),
        ),
        "summary": _selection_summary(payload, normalized_items),
    }


def handle_ellipses_select(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按一基位置和可选数值过滤选择 ellipses.v1。"""

    payload = require_ellipses_payload(request.input_values.get("ellipses"))
    selected = _select_items(payload["items"], request=request)
    normalized_items = [
        {**item, "ellipse_index": index}
        for index, item in enumerate(selected, start=1)
    ]
    return {
        "ellipses": build_ellipses_payload(
            items=normalized_items,
            coordinate_space=str(payload["coordinate_space"]),
            unit=str(payload["unit"]),
            source_image=payload.get("source_image"),
            source_object_key=_optional_text(payload.get("source_object_key")),
        ),
        "summary": _selection_summary(payload, normalized_items),
    }


def handle_transform_create(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """创建 rigid、similarity、affine 或 homography 二维变换。"""

    _cv2_module, np_module = require_opencv_imports()
    transform_kind = _require_choice(
        request.parameters.get("transform_kind", "rigid"),
        field_name="transform_kind",
        supported={"rigid", "similarity", "affine", "homography"},
    )
    matrix = _create_transform_matrix(
        request=request,
        transform_kind=transform_kind,
        np_module=np_module,
    )
    return _transform_output(
        matrix=matrix,
        transform_kind=transform_kind,
        source_coordinate_space=require_coordinate_space(
            request.parameters.get("source_coordinate_space"),
            field_name="source_coordinate_space",
        ),
        target_coordinate_space=require_coordinate_space(
            request.parameters.get("target_coordinate_space"),
            field_name="target_coordinate_space",
        ),
        np_module=np_module,
    )


def handle_transform_compose(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按输入顺序组合多个 planar-transform.v1。"""

    _cv2_module, np_module = require_opencv_imports()
    raw_transforms = request.input_values.get("transforms")
    if not isinstance(raw_transforms, tuple) or len(raw_transforms) < 2:
        raise InvalidRequestError("Transform Compose 至少需要两个 transforms 输入")
    transforms = [require_planar_transform_payload(item) for item in raw_transforms]
    composed = np_module.eye(3, dtype=np_module.float64)
    for transform_index, transform in enumerate(transforms):
        if transform_index > 0:
            previous = transforms[transform_index - 1]
            if previous["target_coordinate_space"] != transform["source_coordinate_space"]:
                raise InvalidRequestError("Transform Compose 的相邻坐标空间不连续")
        composed = np_module.asarray(transform["matrix_3x3"], dtype=np_module.float64) @ composed
    return _transform_output(
        matrix=composed,
        transform_kind="composed",
        source_coordinate_space=str(transforms[0]["source_coordinate_space"]),
        target_coordinate_space=str(transforms[-1]["target_coordinate_space"]),
        np_module=np_module,
        extra_summary={"transform_count": len(transforms)},
    )


def handle_transform_invert(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """反演 planar-transform.v1，并明确拒绝奇异矩阵。"""

    _cv2_module, np_module = require_opencv_imports()
    transform = require_planar_transform_payload(request.input_values.get("transform"))
    matrix = np_module.asarray(transform["matrix_3x3"], dtype=np_module.float64)
    determinant = float(np_module.linalg.det(matrix))
    if not math.isfinite(determinant) or abs(determinant) <= 1e-12:
        raise InvalidRequestError("Transform Invert 不能反演奇异矩阵")
    return _transform_output(
        matrix=np_module.linalg.inv(matrix),
        transform_kind=f"inverse-{transform['transform_kind']}",
        source_coordinate_space=str(transform["target_coordinate_space"]),
        target_coordinate_space=str(transform["source_coordinate_space"]),
        np_module=np_module,
    )


def handle_transform_points(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用明确方向的 planar transform 变换 points.v1。"""

    return _handle_points_transform(request, source_unit=None, target_unit=None)


def handle_pixel_to_world(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用平面标定 transform 把像素点转换到世界平面。"""

    target_unit = _require_choice(
        request.parameters.get("world_unit", "millimeter"),
        field_name="world_unit",
        supported={"millimeter", "meter", "unitless"},
    )
    return _handle_points_transform(
        request,
        source_unit="pixel",
        target_unit=target_unit,
    )


def handle_world_to_pixel(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用平面标定 transform 把世界平面点投影到像素坐标。"""

    points = require_points_payload(request.input_values.get("points"))
    if points["unit"] == "pixel":
        raise InvalidRequestError("World To Pixel 的输入点不能已经是 pixel 单位")
    return _handle_points_transform(request, source_unit=None, target_unit="pixel")


def handle_line_line_relation(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算两条无限直线的夹角、交点和平行距离。"""

    first_payload = require_lines_payload(request.input_values.get("first_lines"))
    second_payload = require_lines_payload(request.input_values.get("second_lines"))
    coordinate_space, unit = _require_same_context(first_payload, second_payload)
    first = _select_one(first_payload["items"], request.parameters.get("first_index"), "first_index")
    second = _select_one(second_payload["items"], request.parameters.get("second_index"), "second_index")
    first_start, first_end = _line_points(first)
    second_start, second_end = _line_points(second)
    first_vector = (first_end[0] - first_start[0], first_end[1] - first_start[1])
    second_vector = (second_end[0] - second_start[0], second_end[1] - second_start[1])
    denominator = _cross(first_vector, second_vector)
    length_product = math.hypot(*first_vector) * math.hypot(*second_vector)
    if length_product <= 1e-12:
        raise InvalidRequestError("Line Line Relation 不能处理零长度直线")
    normalized_cross = denominator / length_product
    angle_deg = math.degrees(math.acos(min(1.0, abs(_dot(first_vector, second_vector)) / length_product)))
    intersections: list[list[float]] = []
    if abs(normalized_cross) > 1e-10:
        delta = (second_start[0] - first_start[0], second_start[1] - first_start[1])
        parameter = _cross(delta, second_vector) / denominator
        intersections.append(
            [first_start[0] + parameter * first_vector[0], first_start[1] + parameter * first_vector[1]]
        )
        distance = 0.0
        relation = "intersecting"
    else:
        distance = abs(_cross((second_start[0] - first_start[0], second_start[1] - first_start[1]), first_vector)) / math.hypot(*first_vector)
        relation = "coincident" if distance <= 1e-10 else "parallel"
    return _relation_output(
        kind="line-line",
        coordinate_space=coordinate_space,
        unit=unit,
        values={
            "relation": relation,
            "angle_degrees": angle_deg,
            "distance": distance,
            "intersection_points": intersections,
        },
    )


def handle_point_circle_relation(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算点到圆周的有符号距离和最近点。"""

    points = require_points_payload(request.input_values.get("points"))
    circles = require_circles_payload(request.input_values.get("circles"))
    coordinate_space, unit = _require_same_context(points, circles)
    point = _select_one(points["items"], request.parameters.get("point_index"), "point_index")
    circle = _select_one(circles["items"], request.parameters.get("circle_index"), "circle_index")
    point_xy = tuple(point["xy"])
    center_xy = tuple(circle["center_xy"])
    radius = float(circle["radius"])
    dx = point_xy[0] - center_xy[0]
    dy = point_xy[1] - center_xy[1]
    center_distance = math.hypot(dx, dy)
    signed_distance = center_distance - radius
    closest_point = None
    if center_distance > 1e-12:
        closest_point = [
            center_xy[0] + radius * dx / center_distance,
            center_xy[1] + radius * dy / center_distance,
        ]
    return _relation_output(
        kind="point-circle",
        coordinate_space=coordinate_space,
        unit=unit,
        values={
            "relation": "outside" if signed_distance > 0 else "inside" if signed_distance < 0 else "on-circle",
            "center_distance": center_distance,
            "signed_distance": signed_distance,
            "distance": abs(signed_distance),
            "closest_point": closest_point,
        },
    )


def handle_line_circle_relation(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算无限直线与圆的交点、距离和相切状态。"""

    lines = require_lines_payload(request.input_values.get("lines"))
    circles = require_circles_payload(request.input_values.get("circles"))
    coordinate_space, unit = _require_same_context(lines, circles)
    line = _select_one(lines["items"], request.parameters.get("line_index"), "line_index")
    circle = _select_one(circles["items"], request.parameters.get("circle_index"), "circle_index")
    start, end = _line_points(line)
    direction = (end[0] - start[0], end[1] - start[1])
    center = tuple(circle["center_xy"])
    radius = float(circle["radius"])
    a = _dot(direction, direction)
    if a <= 1e-12:
        raise InvalidRequestError("Line Circle Relation 不能处理零长度直线")
    offset = (start[0] - center[0], start[1] - center[1])
    b = 2.0 * _dot(direction, offset)
    c = _dot(offset, offset) - radius * radius
    discriminant = b * b - 4.0 * a * c
    intersections: list[list[float]] = []
    tolerance = 1e-10 * max(1.0, b * b, abs(4.0 * a * c))
    if discriminant >= -tolerance:
        root = math.sqrt(max(0.0, discriminant))
        parameters = [(-b - root) / (2.0 * a)]
        if root > tolerance:
            parameters.append((-b + root) / (2.0 * a))
        intersections = [
            [start[0] + value * direction[0], start[1] + value * direction[1]]
            for value in parameters
        ]
    line_distance = abs(_cross((center[0] - start[0], center[1] - start[1]), direction)) / math.sqrt(a)
    relation = "intersecting" if len(intersections) == 2 else "tangent" if intersections else "disjoint"
    return _relation_output(
        kind="line-circle",
        coordinate_space=coordinate_space,
        unit=unit,
        values={
            "relation": relation,
            "center_to_line_distance": line_distance,
            "clearance": line_distance - radius,
            "intersection_points": intersections,
        },
    )


def handle_circle_circle_relation(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算两个圆的相对状态、间隙和交点。"""

    first_payload = require_circles_payload(request.input_values.get("first_circles"))
    second_payload = require_circles_payload(request.input_values.get("second_circles"))
    coordinate_space, unit = _require_same_context(first_payload, second_payload)
    first = _select_one(first_payload["items"], request.parameters.get("first_index"), "first_index")
    second = _select_one(second_payload["items"], request.parameters.get("second_index"), "second_index")
    first_center = tuple(first["center_xy"])
    second_center = tuple(second["center_xy"])
    first_radius = float(first["radius"])
    second_radius = float(second["radius"])
    dx = second_center[0] - first_center[0]
    dy = second_center[1] - first_center[1]
    distance = math.hypot(dx, dy)
    intersections: list[list[float]] = []
    tolerance = 1e-10 * max(1.0, distance, first_radius, second_radius)
    if distance <= tolerance and abs(first_radius - second_radius) <= tolerance:
        relation = "coincident"
    elif distance > first_radius + second_radius + tolerance:
        relation = "separate"
    elif distance < abs(first_radius - second_radius) - tolerance:
        relation = "contained"
    elif distance <= tolerance:
        relation = "concentric"
    else:
        a = (first_radius**2 - second_radius**2 + distance**2) / (2.0 * distance)
        height_squared = max(0.0, first_radius**2 - a**2)
        height = math.sqrt(height_squared)
        base_x = first_center[0] + a * dx / distance
        base_y = first_center[1] + a * dy / distance
        perpendicular_x = -dy / distance
        perpendicular_y = dx / distance
        intersections.append([base_x + height * perpendicular_x, base_y + height * perpendicular_y])
        if height > tolerance:
            intersections.append([base_x - height * perpendicular_x, base_y - height * perpendicular_y])
        relation = "intersecting" if len(intersections) == 2 else "tangent"
    return _relation_output(
        kind="circle-circle",
        coordinate_space=coordinate_space,
        unit=unit,
        values={
            "relation": relation,
            "center_distance": distance,
            "external_clearance": distance - first_radius - second_radius,
            "intersection_points": intersections,
        },
    )


def _handle_points_transform(
    request: WorkflowNodeExecutionRequest,
    *,
    source_unit: str | None,
    target_unit: str | None,
) -> dict[str, object]:
    """共享 points 平面变换实现。"""

    _cv2_module, np_module = require_opencv_imports()
    points = require_points_payload(request.input_values.get("points"))
    transform = require_planar_transform_payload(request.input_values.get("transform"))
    if points["coordinate_space"] != transform["source_coordinate_space"]:
        raise InvalidRequestError("Points 的 coordinate_space 与 Transform source 不一致")
    if source_unit is not None and points["unit"] != source_unit:
        raise InvalidRequestError(f"当前节点要求 points.unit 为 {source_unit}")
    resolved_target_unit = target_unit or _read_optional_unit(
        request.parameters.get("target_unit"),
        default=str(points["unit"]),
    )
    matrix = np_module.asarray(transform["matrix_3x3"], dtype=np_module.float64)
    transformed_items: list[dict[str, object]] = []
    for item in points["items"]:
        x_value, y_value = item["xy"]
        homogeneous = matrix @ np_module.asarray([x_value, y_value, 1.0], dtype=np_module.float64)
        denominator = float(homogeneous[2])
        if abs(denominator) <= 1e-12:
            raise InvalidRequestError("Transform Points 产生了无穷远点")
        transformed_items.append(
            {
                **item,
                "xy": [float(homogeneous[0] / denominator), float(homogeneous[1] / denominator)],
            }
        )
    output_points = build_points_payload(
        items=transformed_items,
        coordinate_space=str(transform["target_coordinate_space"]),
        unit=resolved_target_unit,
    )
    return {
        "points": output_points,
        "summary": build_value_payload(
            {
                "count": len(transformed_items),
                "source_coordinate_space": transform["source_coordinate_space"],
                "target_coordinate_space": transform["target_coordinate_space"],
                "source_unit": points["unit"],
                "target_unit": resolved_target_unit,
            }
        ),
    }


def _create_transform_matrix(
    *,
    request: WorkflowNodeExecutionRequest,
    transform_kind: str,
    np_module: Any,
) -> Any:
    """按类型创建 3x3 float64 矩阵。"""

    if transform_kind in {"rigid", "similarity"}:
        angle = math.radians(
            require_number(request.parameters.get("angle_degrees", 0.0), field_name="angle_degrees")
        )
        scale = (
            _require_positive_number(request.parameters.get("scale", 1.0), field_name="scale")
            if transform_kind == "similarity"
            else 1.0
        )
        translation_x = require_number(
            request.parameters.get("translation_x", 0.0), field_name="translation_x"
        )
        translation_y = require_number(
            request.parameters.get("translation_y", 0.0), field_name="translation_y"
        )
        cosine = scale * math.cos(angle)
        sine = scale * math.sin(angle)
        return np_module.asarray(
            [[cosine, -sine, translation_x], [sine, cosine, translation_y], [0.0, 0.0, 1.0]],
            dtype=np_module.float64,
        )
    matrix_parameter = "matrix_2x3" if transform_kind == "affine" else "matrix_3x3"
    raw_matrix = request.parameters.get(matrix_parameter)
    expected_rows, expected_columns = ((2, 3) if transform_kind == "affine" else (3, 3))
    matrix = _require_matrix(
        raw_matrix,
        rows=expected_rows,
        columns=expected_columns,
        field_name=matrix_parameter,
        np_module=np_module,
    )
    if transform_kind == "affine":
        matrix = np_module.vstack((matrix, np_module.asarray([0.0, 0.0, 1.0])))
    return matrix


def _transform_output(
    *,
    matrix: Any,
    transform_kind: str,
    source_coordinate_space: str,
    target_coordinate_space: str,
    np_module: Any,
    extra_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    """校验矩阵可逆并输出双向 planar transform。"""

    determinant = float(np_module.linalg.det(matrix))
    if not math.isfinite(determinant) or abs(determinant) <= 1e-12:
        raise InvalidRequestError("二维变换矩阵奇异或不可逆")
    condition_number = float(np_module.linalg.cond(matrix))
    if not math.isfinite(condition_number) or condition_number > 1e12:
        raise InvalidRequestError("二维变换矩阵病态，condition number 过大")
    inverse = np_module.linalg.inv(matrix)
    payload = build_planar_transform_payload(
        matrix_3x3=matrix.astype(float).tolist(),
        inverse_matrix_3x3=inverse.astype(float).tolist(),
        source_coordinate_space=source_coordinate_space,
        target_coordinate_space=target_coordinate_space,
        match_count=0,
        inlier_count=0,
        inlier_match_ids=[],
        reprojection_error=None,
        source_a_image=None,
        source_b_image=None,
        transform_kind=transform_kind,
    )
    return {
        "transform": payload,
        "summary": build_value_payload(
            {
                "transform_kind": transform_kind,
                "determinant": determinant,
                "condition_number": condition_number,
                **dict(extra_summary or {}),
            }
        ),
    }


def _select_items(
    items: list[dict[str, object]],
    *,
    request: WorkflowNodeExecutionRequest,
) -> list[dict[str, object]]:
    """按一基位置数组与可选数值字段范围筛选。"""

    raw_indexes = request.parameters.get("indexes")
    if raw_indexes in (None, []):
        selected = [dict(item) for item in items]
    else:
        if not isinstance(raw_indexes, list):
            raise InvalidRequestError("indexes 必须是一基整数数组")
        indexes = [_require_one_based_index(value, field_name="indexes") for value in raw_indexes]
        if len(set(indexes)) != len(indexes):
            raise InvalidRequestError("indexes 不能重复")
        if any(index > len(items) for index in indexes):
            raise InvalidRequestError("indexes 超出输入 items 数量")
        selected = [dict(items[index - 1]) for index in indexes]
    filter_field = _optional_text(request.parameters.get("filter_field"))
    if filter_field is None:
        return selected
    minimum = request.parameters.get("minimum")
    maximum = request.parameters.get("maximum")
    minimum_value = require_number(minimum, field_name="minimum") if minimum is not None else None
    maximum_value = require_number(maximum, field_name="maximum") if maximum is not None else None
    if minimum_value is None and maximum_value is None:
        raise InvalidRequestError("设置 filter_field 时必须提供 minimum 或 maximum")
    if minimum_value is not None and maximum_value is not None and minimum_value > maximum_value:
        raise InvalidRequestError("minimum 不能大于 maximum")
    filtered: list[dict[str, object]] = []
    for item in selected:
        if filter_field not in item:
            raise InvalidRequestError("filter_field 在 item 中不存在")
        field_value = require_number(item[filter_field], field_name=filter_field)
        if minimum_value is not None and field_value < minimum_value:
            continue
        if maximum_value is not None and field_value > maximum_value:
            continue
        filtered.append(item)
    return filtered


def _selection_summary(
    source_payload: dict[str, object],
    selected_items: list[dict[str, object]],
) -> dict[str, object]:
    """构造选择摘要。"""

    return build_value_payload(
        {
            "source_count": len(source_payload["items"]),
            "selected_count": len(selected_items),
            "coordinate_space": source_payload["coordinate_space"],
            "unit": source_payload["unit"],
        }
    )


def _relation_output(
    *,
    kind: str,
    coordinate_space: str,
    unit: str,
    values: dict[str, object],
) -> dict[str, object]:
    """构造通用 geometry-relation measurements.v1。"""

    item = {
        "measurement_id": f"{kind}-1",
        "measurement_kind": kind,
        "coordinate_space": coordinate_space,
        "unit": unit,
        "values": values,
    }
    return {
        "measurements": {
            "coordinate_space": coordinate_space,
            "unit": unit,
            "count": 1,
            "items": [item],
            "summary": {"measurement_kind": kind},
        },
        "summary": build_value_payload(values),
    }


def _read_input_value_or_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str,
) -> object:
    """优先读取 value.v1 输入，否则读取同名参数。"""

    input_payload = request.input_values.get(name)
    if input_payload is not None:
        return require_value_payload(input_payload, field_name=name)["value"]
    return request.parameters.get(name)


def _read_geometry_context(request: WorkflowNodeExecutionRequest) -> tuple[str, str]:
    """读取坐标空间和单位。"""

    return (
        require_coordinate_space(request.parameters.get("coordinate_space")),
        require_point_unit(request.parameters.get("unit", "pixel")),
    )


def _require_context_matches(
    *,
    coordinate_space: str,
    unit: str,
    payload: dict[str, object],
) -> None:
    """校验显式参数与输入 geometry 上下文一致。"""

    if payload["coordinate_space"] != coordinate_space or payload["unit"] != unit:
        raise InvalidRequestError("输入几何的 coordinate_space/unit 与节点参数不一致")


def _require_same_context(
    first: dict[str, object],
    second: dict[str, object],
) -> tuple[str, str]:
    """校验两类几何来自同一坐标空间和单位。"""

    if first.get("coordinate_space") != second.get("coordinate_space"):
        raise InvalidRequestError("几何关系输入的 coordinate_space 必须一致")
    if first.get("unit") != second.get("unit"):
        raise InvalidRequestError("几何关系输入的 unit 必须一致")
    return str(first["coordinate_space"]), str(first["unit"])


def _build_line_item(
    *,
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    line_index: int,
) -> dict[str, object]:
    """构造现有 lines.v1 兼容字段。"""

    dx = end_xy[0] - start_xy[0]
    dy = end_xy[1] - start_xy[1]
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        raise InvalidRequestError("Line Create 的两个端点不能重合")
    return {
        "line_index": line_index,
        "start_xy": list(start_xy),
        "end_xy": list(end_xy),
        "length_pixels": length,
        "angle_deg": math.degrees(math.atan2(dy, dx)),
        "midpoint_xy": [(start_xy[0] + end_xy[0]) / 2.0, (start_xy[1] + end_xy[1]) / 2.0],
        "bbox_xyxy": [min(start_xy[0], end_xy[0]), min(start_xy[1], end_xy[1]), max(start_xy[0], end_xy[0]), max(start_xy[1], end_xy[1])],
    }


def _build_circle_item(
    *,
    center_xy: tuple[float, float],
    radius: float,
    circle_index: int,
) -> dict[str, object]:
    """构造现有 circles.v1 兼容字段。"""

    return {
        "circle_index": circle_index,
        "center_xy": list(center_xy),
        "radius": radius,
        "diameter": radius * 2.0,
        "area": math.pi * radius * radius,
        "bbox_xyxy": [center_xy[0] - radius, center_xy[1] - radius, center_xy[0] + radius, center_xy[1] + radius],
    }


def _ellipse_axis_aligned_bbox(
    *,
    center_xy: tuple[float, float],
    major_axis: float,
    minor_axis: float,
    angle_deg: float,
) -> list[float]:
    """计算旋转椭圆的轴对齐包围框。"""

    angle = math.radians(angle_deg)
    semi_major = major_axis / 2.0
    semi_minor = minor_axis / 2.0
    extent_x = math.sqrt((semi_major * math.cos(angle)) ** 2 + (semi_minor * math.sin(angle)) ** 2)
    extent_y = math.sqrt((semi_major * math.sin(angle)) ** 2 + (semi_minor * math.cos(angle)) ** 2)
    return [center_xy[0] - extent_x, center_xy[1] - extent_y, center_xy[0] + extent_x, center_xy[1] + extent_y]


def _select_one(
    items: list[dict[str, object]],
    raw_index: object,
    field_name: str,
) -> dict[str, object]:
    """按一基位置选择一个 item。"""

    index = _require_one_based_index(raw_index if raw_index is not None else 1, field_name=field_name)
    if index > len(items):
        raise InvalidRequestError(f"{field_name} 超出输入数量")
    return dict(items[index - 1])


def _require_one_based_index(raw_value: object, *, field_name: str) -> int:
    """读取一基正整数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    return raw_value


def _require_xy(raw_value: object, *, field_name: str) -> tuple[float, float]:
    """读取二维有限坐标。"""

    if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 2:
        raise InvalidRequestError(f"{field_name} 必须是 [x, y]")
    return (
        require_number(raw_value[0], field_name=f"{field_name}[0]"),
        require_number(raw_value[1], field_name=f"{field_name}[1]"),
    )


def _require_positive_number(raw_value: object, *, field_name: str) -> float:
    """读取严格正有限数值。"""

    value = require_number(raw_value, field_name=field_name)
    if value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return float(value)


def _require_choice(raw_value: object, *, field_name: str, supported: set[str]) -> str:
    """读取受控字符串枚举。"""

    if not isinstance(raw_value, str) or raw_value.strip().lower() not in supported:
        raise InvalidRequestError(f"{field_name} 不在支持列表中")
    return raw_value.strip().lower()


def _read_optional_unit(raw_value: object, *, default: str) -> str:
    """读取可选目标单位。"""

    return require_point_unit(default if raw_value is None else raw_value)


def _require_matrix(
    raw_value: object,
    *,
    rows: int,
    columns: int,
    field_name: str,
    np_module: Any,
) -> Any:
    """读取固定形状的有限矩阵。"""

    if not isinstance(raw_value, list) or len(raw_value) != rows:
        raise InvalidRequestError(f"{field_name} 必须是 {rows}x{columns} 矩阵")
    values: list[list[float]] = []
    for row_index, row in enumerate(raw_value):
        if not isinstance(row, list) or len(row) != columns:
            raise InvalidRequestError(f"{field_name}[{row_index}] 长度必须为 {columns}")
        values.append(
            [
                require_number(cell, field_name=f"{field_name}[{row_index}][{column_index}]")
                for column_index, cell in enumerate(row)
            ]
        )
    return np_module.asarray(values, dtype=np_module.float64)


def _line_points(line: dict[str, object]) -> tuple[tuple[float, float], tuple[float, float]]:
    """读取规范线段端点。"""

    return tuple(line["start_xy"]), tuple(line["end_xy"])


def _dot(first: tuple[float, float], second: tuple[float, float]) -> float:
    """二维点积。"""

    return first[0] * second[0] + first[1] * second[1]


def _cross(first: tuple[float, float], second: tuple[float, float]) -> float:
    """二维叉积标量。"""

    return first[0] * second[1] - first[1] * second[0]


def _optional_text(raw_value: object) -> str | None:
    """读取可选非空文本。"""

    return raw_value.strip() if isinstance(raw_value, str) and raw_value.strip() else None


NODE_HANDLERS: tuple[
    tuple[str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]], ...
] = (
    (POINT_CREATE_NODE_TYPE_ID, handle_point_create),
    (LINE_CREATE_NODE_TYPE_ID, handle_line_create),
    (CIRCLE_CREATE_NODE_TYPE_ID, handle_circle_create),
    (ELLIPSE_CREATE_NODE_TYPE_ID, handle_ellipse_create),
    (POINTS_SELECT_NODE_TYPE_ID, handle_points_select),
    (LINES_SELECT_NODE_TYPE_ID, handle_lines_select),
    (CIRCLES_SELECT_NODE_TYPE_ID, handle_circles_select),
    (ELLIPSES_SELECT_NODE_TYPE_ID, handle_ellipses_select),
    (TRANSFORM_CREATE_NODE_TYPE_ID, handle_transform_create),
    (TRANSFORM_COMPOSE_NODE_TYPE_ID, handle_transform_compose),
    (TRANSFORM_INVERT_NODE_TYPE_ID, handle_transform_invert),
    (TRANSFORM_POINTS_NODE_TYPE_ID, handle_transform_points),
    (PIXEL_TO_WORLD_NODE_TYPE_ID, handle_pixel_to_world),
    (WORLD_TO_PIXEL_NODE_TYPE_ID, handle_world_to_pixel),
    (LINE_LINE_RELATION_NODE_TYPE_ID, handle_line_line_relation),
    (POINT_CIRCLE_RELATION_NODE_TYPE_ID, handle_point_circle_relation),
    (LINE_CIRCLE_RELATION_NODE_TYPE_ID, handle_line_circle_relation),
    (CIRCLE_CIRCLE_RELATION_NODE_TYPE_ID, handle_circle_circle_relation),
)


__all__ = ["NODE_HANDLERS"]
