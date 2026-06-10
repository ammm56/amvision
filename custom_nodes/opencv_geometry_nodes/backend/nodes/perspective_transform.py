"""Perspective Transform 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._roi_node_support import bbox_to_polygon_xy, require_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_optional_object_key,
    normalize_resize_interpolation,
    require_number,
    require_opencv_imports,
    require_positive_int,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.perspective-transform"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按四点透视关系把输入图片矫正到规则矩形输出。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _source_object_key, image_matrix = load_image_matrix(request)
    source_points, source_kind, source_summary = _resolve_source_points(request)
    estimated_output_width, estimated_output_height = _estimate_output_size(source_points)
    output_width, output_height, output_size_source = _resolve_output_size(
        request,
        estimated_output_width=estimated_output_width,
        estimated_output_height=estimated_output_height,
    )
    raw_interpolation = request.parameters.get("interpolation")
    interpolation = (
        cv2_module.INTER_LINEAR
        if raw_interpolation in {None, ""}
        else normalize_resize_interpolation(raw_interpolation, cv2_module=cv2_module)
    )
    border_mode = _resolve_border_mode(request.parameters.get("border_mode"), cv2_module=cv2_module)
    border_value = _read_optional_border_value(request.parameters.get("border_value"))

    source_point_matrix = np_module.array(source_points, dtype=np_module.float32)
    target_point_matrix = np_module.array(
        [
            [0.0, 0.0],
            [float(output_width - 1), 0.0],
            [float(output_width - 1), float(output_height - 1)],
            [0.0, float(output_height - 1)],
        ],
        dtype=np_module.float32,
    )
    perspective_matrix = cv2_module.getPerspectiveTransform(source_point_matrix, target_point_matrix)
    border_value_argument = (
        (border_value, border_value, border_value) if len(image_matrix.shape) == 3 else border_value
    )
    output_image = cv2_module.warpPerspective(
        image_matrix,
        perspective_matrix,
        (output_width, output_height),
        flags=interpolation,
        borderMode=border_mode,
        borderValue=border_value_argument,
    )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=output_image,
        error_message="OpenCV perspective-transform 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="perspective-transform",
        output_extension=".png",
        width=int(output_width),
        height=int(output_height),
        media_type="image/png",
    )
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "source_kind": source_kind,
                "source_points": [[round(point_x, 4), round(point_y, 4)] for point_x, point_y in source_points],
                "source_bbox_xyxy": _build_bbox_xyxy(source_points),
                "source_point_order": "top-left,top-right,bottom-right,bottom-left",
                "estimated_output_width": int(estimated_output_width),
                "estimated_output_height": int(estimated_output_height),
                "output_width": int(output_width),
                "output_height": int(output_height),
                "output_size_source": output_size_source,
                "transform_matrix": [
                    [round(float(cell_value), 6) for cell_value in row_values.tolist()]
                    for row_values in perspective_matrix
                ],
                **source_summary,
            }
        ),
    }


def _resolve_source_points(
    request: WorkflowNodeExecutionRequest,
) -> tuple[list[tuple[float, float]], str, dict[str, object]]:
    """解析透视矫正的源四点。"""

    raw_roi_payload = request.input_values.get("roi")
    if raw_roi_payload is not None:
        roi_payload = require_roi_payload(raw_roi_payload, node_id=request.node_id)
        if roi_payload["roi_kind"] == "bbox":
            source_points = _normalize_quad_points(
                bbox_to_polygon_xy(roi_payload["bbox_xyxy"]),
                field_name="roi.bbox_xyxy",
            )
        else:
            source_points = _normalize_quad_points(
                roi_payload["polygon_xy"],
                field_name="roi.polygon_xy",
            )
        return (
            source_points,
            "roi",
            {
                "roi_id": roi_payload["roi_id"],
                "roi_kind": roi_payload["roi_kind"],
            },
        )

    raw_source_points = request.parameters.get("source_points")
    if raw_source_points is None or raw_source_points == "":
        raise InvalidRequestError("perspective-transform 节点要求 roi 输入或 source_points 参数至少提供一个")
    return _normalize_quad_points(raw_source_points, field_name="source_points"), "parameters", {}


def _normalize_quad_points(raw_value: object, *, field_name: str) -> list[tuple[float, float]]:
    """把输入四点规整为左上、右上、右下、左下顺序。"""

    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise InvalidRequestError(f"{field_name} 必须是恰好 4 个点的数组")

    normalized_points: list[tuple[float, float]] = []
    for point_index, point_value in enumerate(raw_value):
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError(f"{field_name}[{point_index}] 必须是长度为 2 的坐标数组")
        point_x = require_number(point_value[0], field_name=f"{field_name}[{point_index}][0]")
        point_y = require_number(point_value[1], field_name=f"{field_name}[{point_index}][1]")
        normalized_points.append((float(point_x), float(point_y)))

    ordered_points = _order_quad_points(normalized_points)
    polygon_area = _compute_polygon_area(ordered_points)
    if polygon_area <= 1.0:
        raise InvalidRequestError(f"{field_name} 形成的四边形面积必须大于 1")
    return ordered_points


def _order_quad_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """把四点排序为左上、右上、右下、左下。"""

    if len({(round(point_x, 6), round(point_y, 6)) for point_x, point_y in points}) != 4:
        raise InvalidRequestError("perspective-transform 的四点不能重复")

    centroid_x = sum(point_x for point_x, _point_y in points) / 4.0
    centroid_y = sum(point_y for _point_x, point_y in points) / 4.0
    sorted_points = sorted(
        points,
        key=lambda point: math.atan2(point[1] - centroid_y, point[0] - centroid_x),
    )
    start_index = min(range(4), key=lambda index: sorted_points[index][0] + sorted_points[index][1])
    ordered_points = sorted_points[start_index:] + sorted_points[:start_index]
    if ordered_points[1][0] < ordered_points[3][0]:
        ordered_points = [ordered_points[0], ordered_points[3], ordered_points[2], ordered_points[1]]
    return ordered_points


def _compute_polygon_area(points: list[tuple[float, float]]) -> float:
    """计算四边形面积。"""

    signed_area = 0.0
    point_count = len(points)
    for point_index in range(point_count):
        current_x, current_y = points[point_index]
        next_x, next_y = points[(point_index + 1) % point_count]
        signed_area += current_x * next_y - next_x * current_y
    return abs(signed_area) / 2.0


def _estimate_output_size(source_points: list[tuple[float, float]]) -> tuple[int, int]:
    """按四边形边长估算规则化后的输出宽高。"""

    top_width = _point_distance(source_points[0], source_points[1])
    bottom_width = _point_distance(source_points[3], source_points[2])
    left_height = _point_distance(source_points[0], source_points[3])
    right_height = _point_distance(source_points[1], source_points[2])
    estimated_width = max(1, int(math.ceil(max(top_width, bottom_width))))
    estimated_height = max(1, int(math.ceil(max(left_height, right_height))))
    return estimated_width, estimated_height


def _point_distance(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    """计算两点欧氏距离。"""

    return math.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])


def _resolve_output_size(
    request: WorkflowNodeExecutionRequest,
    *,
    estimated_output_width: int,
    estimated_output_height: int,
) -> tuple[int, int, str]:
    """解析最终输出宽高。"""

    raw_output_width = request.parameters.get("output_width")
    raw_output_height = request.parameters.get("output_height")
    if raw_output_width in {None, ""} and raw_output_height in {None, ""}:
        return estimated_output_width, estimated_output_height, "estimated"
    if raw_output_width in {None, ""}:
        return (
            estimated_output_width,
            require_positive_int(raw_output_height, field_name="output_height"),
            "mixed",
        )
    if raw_output_height in {None, ""}:
        return (
            require_positive_int(raw_output_width, field_name="output_width"),
            estimated_output_height,
            "mixed",
        )
    return (
        require_positive_int(raw_output_width, field_name="output_width"),
        require_positive_int(raw_output_height, field_name="output_height"),
        "parameters",
    )


def _build_bbox_xyxy(source_points: list[tuple[float, float]]) -> list[float]:
    """根据四点计算外接 bbox。"""

    x_values = [point_x for point_x, _point_y in source_points]
    y_values = [point_y for _point_x, point_y in source_points]
    return [
        round(min(x_values), 4),
        round(min(y_values), 4),
        round(max(x_values), 4),
        round(max(y_values), 4),
    ]


def _resolve_border_mode(raw_value: object, *, cv2_module) -> int:
    """解析边界填充模式。"""

    if raw_value in {None, ""}:
        return cv2_module.BORDER_CONSTANT
    if not isinstance(raw_value, str):
        raise InvalidRequestError("border_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value == "constant":
        return cv2_module.BORDER_CONSTANT
    if normalized_value == "replicate":
        return cv2_module.BORDER_REPLICATE
    if normalized_value == "reflect":
        return cv2_module.BORDER_REFLECT
    if normalized_value == "reflect101":
        return cv2_module.BORDER_REFLECT_101
    if normalized_value == "wrap":
        return cv2_module.BORDER_WRAP
    raise InvalidRequestError("border_mode 仅支持 constant、replicate、reflect、reflect101 或 wrap")


def _read_optional_border_value(raw_value: object) -> int:
    """读取边界填充值。"""

    if raw_value in {None, ""}:
        return 0
    return require_uint8_int(raw_value, field_name="border_value")
