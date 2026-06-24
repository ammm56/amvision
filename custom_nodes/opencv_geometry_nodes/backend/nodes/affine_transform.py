"""Affine Transform 节点实现。"""

from __future__ import annotations

import math
from typing import Any

from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    extract_value_by_path,
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    normalize_resize_interpolation,
    require_number,
    require_positive_int,
    require_uint8_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.affine-transform"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按仿射矩阵或三对点关系对输入图片执行几何矫正。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _source_object_key, image_matrix = load_image_matrix(request)
    transform_object, source_kind = _resolve_transform_object(request)
    affine_matrix, transform_kind, transform_summary = _resolve_affine_matrix(
        request,
        transform_object=transform_object,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    fit_output_bounds = _read_bool_config_field(
        transform_object=transform_object,
        field_name="fit_output_bounds",
        parameter_value=request.parameters.get("fit_output_bounds"),
        default_value=False,
    )
    output_width, output_height, output_size_source, adjusted_matrix, bounds_summary = _resolve_output_shape(
        request,
        transform_object=transform_object,
        affine_matrix=affine_matrix,
        image_width=int(image_matrix.shape[1]),
        image_height=int(image_matrix.shape[0]),
        fit_output_bounds=fit_output_bounds,
        np_module=np_module,
    )
    raw_interpolation = request.parameters.get("interpolation")
    interpolation = (
        cv2_module.INTER_LINEAR
        if raw_interpolation in {None, ""}
        else normalize_resize_interpolation(raw_interpolation, cv2_module=cv2_module)
    )
    border_mode = _resolve_border_mode(request.parameters.get("border_mode"), cv2_module=cv2_module)
    border_value = _read_optional_border_value(request.parameters.get("border_value"))
    border_value_argument = (
        (border_value, border_value, border_value) if len(image_matrix.shape) == 3 else border_value
    )
    output_image = cv2_module.warpAffine(
        image_matrix,
        adjusted_matrix,
        (output_width, output_height),
        flags=interpolation,
        borderMode=border_mode,
        borderValue=border_value_argument,
    )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=output_image,
        error_message="OpenCV affine-transform 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="affine-transform",
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
                "transform_kind": transform_kind,
                "fit_output_bounds": fit_output_bounds,
                "source_width": int(image_matrix.shape[1]),
                "source_height": int(image_matrix.shape[0]),
                "output_width": int(output_width),
                "output_height": int(output_height),
                "output_size_source": output_size_source,
                "original_matrix": _serialize_matrix(affine_matrix),
                "applied_matrix": _serialize_matrix(adjusted_matrix),
                **transform_summary,
                **bounds_summary,
            }
        ),
    }


def _resolve_transform_object(request: WorkflowNodeExecutionRequest) -> tuple[dict[str, object] | None, str]:
    """读取可选动态仿射配置对象。"""

    raw_transform_payload = request.input_values.get("transform")
    if raw_transform_payload is None:
        return None, "parameters"
    transform_payload = require_value_payload(raw_transform_payload, field_name="transform")
    transform_path = _read_optional_text(request.parameters.get("transform_path"), field_name="transform_path")
    resolved_value = (
        extract_value_by_path(root=transform_payload["value"], path=transform_path)
        if transform_path is not None
        else transform_payload["value"]
    )
    if not isinstance(resolved_value, dict):
        raise InvalidRequestError("affine-transform 节点的 transform 输入必须解析为对象")
    return dict(resolved_value), "input"


def _resolve_affine_matrix(
    request: WorkflowNodeExecutionRequest,
    *,
    transform_object: dict[str, object] | None,
    cv2_module: Any,
    np_module: Any,
) -> tuple[Any, str, dict[str, object]]:
    """解析仿射矩阵来源。"""

    raw_matrix = _resolve_transform_field_value(
        transform_object=transform_object,
        field_name="matrix_2x3",
        parameter_value=request.parameters.get("matrix_2x3"),
    )
    if not _is_missing_config_value(raw_matrix):
        return (
            _normalize_matrix_2x3(raw_matrix, np_module=np_module),
            "matrix",
            {},
        )

    raw_source_points = _resolve_transform_field_value(
        transform_object=transform_object,
        field_name="source_points",
        parameter_value=request.parameters.get("source_points"),
    )
    raw_target_points = _resolve_transform_field_value(
        transform_object=transform_object,
        field_name="target_points",
        parameter_value=request.parameters.get("target_points"),
    )
    if _is_missing_config_value(raw_source_points) or _is_missing_config_value(raw_target_points):
        raise InvalidRequestError(
            "affine-transform 节点要求 matrix_2x3，或 source_points 与 target_points 至少提供一种方式"
        )
    source_points = _normalize_triangle_points(raw_source_points, field_name="source_points")
    target_points = _normalize_triangle_points(raw_target_points, field_name="target_points")
    affine_matrix = cv2_module.getAffineTransform(
        np_module.array(source_points, dtype=np_module.float32),
        np_module.array(target_points, dtype=np_module.float32),
    )
    return (
        affine_matrix.astype(np_module.float32, copy=False),
        "point-pairs",
        {
            "source_points": [[round(point_x, 4), round(point_y, 4)] for point_x, point_y in source_points],
            "target_points": [[round(point_x, 4), round(point_y, 4)] for point_x, point_y in target_points],
        },
    )


def _resolve_output_shape(
    request: WorkflowNodeExecutionRequest,
    *,
    transform_object: dict[str, object] | None,
    affine_matrix: Any,
    image_width: int,
    image_height: int,
    fit_output_bounds: bool,
    np_module: Any,
) -> tuple[int, int, str, Any, dict[str, object]]:
    """解析最终输出宽高和实际执行矩阵。"""

    min_x, min_y, max_x, max_y = _compute_transformed_bounds(
        affine_matrix=affine_matrix,
        image_width=image_width,
        image_height=image_height,
        np_module=np_module,
    )
    translation_offset_x = -min_x if fit_output_bounds and min_x < 0.0 else 0.0
    translation_offset_y = -min_y if fit_output_bounds and min_y < 0.0 else 0.0
    adjusted_matrix = affine_matrix.copy()
    adjusted_matrix[0, 2] += translation_offset_x
    adjusted_matrix[1, 2] += translation_offset_y
    adjusted_min_x = min_x + translation_offset_x
    adjusted_min_y = min_y + translation_offset_y
    adjusted_max_x = max_x + translation_offset_x
    adjusted_max_y = max_y + translation_offset_y
    fit_width = max(1, int(math.ceil(adjusted_max_x - adjusted_min_x + 1.0)))
    fit_height = max(1, int(math.ceil(adjusted_max_y - adjusted_min_y + 1.0)))

    raw_output_width = _resolve_transform_field_value(
        transform_object=transform_object,
        field_name="output_width",
        parameter_value=request.parameters.get("output_width"),
    )
    raw_output_height = _resolve_transform_field_value(
        transform_object=transform_object,
        field_name="output_height",
        parameter_value=request.parameters.get("output_height"),
    )
    if _is_missing_config_value(raw_output_width) and _is_missing_config_value(raw_output_height):
        if fit_output_bounds:
            output_width = fit_width
            output_height = fit_height
            output_size_source = "fit-bounds"
        else:
            output_width = int(image_width)
            output_height = int(image_height)
            output_size_source = "source-image"
    elif _is_missing_config_value(raw_output_width):
        output_width = fit_width if fit_output_bounds else int(image_width)
        output_height = require_positive_int(raw_output_height, field_name="output_height")
        output_size_source = "mixed"
    elif _is_missing_config_value(raw_output_height):
        output_width = require_positive_int(raw_output_width, field_name="output_width")
        output_height = fit_height if fit_output_bounds else int(image_height)
        output_size_source = "mixed"
    else:
        output_width = require_positive_int(raw_output_width, field_name="output_width")
        output_height = require_positive_int(raw_output_height, field_name="output_height")
        output_size_source = "parameters"

    return (
        int(output_width),
        int(output_height),
        output_size_source,
        adjusted_matrix,
        {
            "fit_bounds_bbox_xyxy": [
                round(float(adjusted_min_x), 4),
                round(float(adjusted_min_y), 4),
                round(float(adjusted_max_x), 4),
                round(float(adjusted_max_y), 4),
            ],
            "fit_bounds_width": int(fit_width),
            "fit_bounds_height": int(fit_height),
            "translation_offset_x": round(float(translation_offset_x), 4),
            "translation_offset_y": round(float(translation_offset_y), 4),
        },
    )


def _compute_transformed_bounds(
    *,
    affine_matrix: Any,
    image_width: int,
    image_height: int,
    np_module: Any,
) -> tuple[float, float, float, float]:
    """计算输入图片四角经过仿射变换后的外接范围。"""

    corner_matrix = np_module.array(
        [
            [0.0, 0.0, 1.0],
            [float(image_width - 1), 0.0, 1.0],
            [float(image_width - 1), float(image_height - 1), 1.0],
            [0.0, float(image_height - 1), 1.0],
        ],
        dtype=np_module.float32,
    )
    transformed_corners = (affine_matrix @ corner_matrix.T).T
    x_values = transformed_corners[:, 0].tolist()
    y_values = transformed_corners[:, 1].tolist()
    return (
        float(min(x_values)),
        float(min(y_values)),
        float(max(x_values)),
        float(max(y_values)),
    )


def _resolve_transform_field_value(
    *,
    transform_object: dict[str, object] | None,
    field_name: str,
    parameter_value: object,
) -> object:
    """优先读取 transform 输入中的字段，否则回退到节点参数。"""

    if transform_object is not None and transform_object.get(field_name) is not None:
        return transform_object.get(field_name)
    return parameter_value


def _normalize_matrix_2x3(raw_value: object, *, np_module: Any):
    """把 2x3 数值矩阵规范化为 float32 ndarray。"""

    if not isinstance(raw_value, list) or len(raw_value) != 2:
        raise InvalidRequestError("matrix_2x3 必须是 2x3 数值矩阵")
    normalized_rows: list[list[float]] = []
    for row_index, row_value in enumerate(raw_value):
        if not isinstance(row_value, list) or len(row_value) != 3:
            raise InvalidRequestError(f"matrix_2x3[{row_index}] 必须是长度为 3 的数组")
        normalized_rows.append(
            [
                require_number(cell_value, field_name=f"matrix_2x3[{row_index}][{column_index}]")
                for column_index, cell_value in enumerate(row_value)
            ]
        )
    return np_module.array(normalized_rows, dtype=np_module.float32)


def _normalize_triangle_points(raw_value: object, *, field_name: str) -> list[tuple[float, float]]:
    """把三点输入规范化为可用于仿射变换的点集。"""

    if not isinstance(raw_value, list) or len(raw_value) != 3:
        raise InvalidRequestError(f"{field_name} 必须是恰好 3 个点的数组")
    normalized_points: list[tuple[float, float]] = []
    for point_index, point_value in enumerate(raw_value):
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError(f"{field_name}[{point_index}] 必须是长度为 2 的坐标数组")
        point_x = require_number(point_value[0], field_name=f"{field_name}[{point_index}][0]")
        point_y = require_number(point_value[1], field_name=f"{field_name}[{point_index}][1]")
        normalized_points.append((float(point_x), float(point_y)))
    if len({(round(point_x, 6), round(point_y, 6)) for point_x, point_y in normalized_points}) != 3:
        raise InvalidRequestError(f"{field_name} 的三点不能重复")
    if _compute_triangle_area(normalized_points) <= 1.0:
        raise InvalidRequestError(f"{field_name} 形成的三角形面积必须大于 1")
    return normalized_points


def _compute_triangle_area(points: list[tuple[float, float]]) -> float:
    """计算三角形面积。"""

    point_a, point_b, point_c = points
    return abs(
        point_a[0] * (point_b[1] - point_c[1])
        + point_b[0] * (point_c[1] - point_a[1])
        + point_c[0] * (point_a[1] - point_b[1])
    ) / 2.0


def _serialize_matrix(matrix: Any) -> list[list[float]]:
    """把二维矩阵规整为可序列化列表。"""

    return [
        [round(float(cell_value), 6) for cell_value in row_values.tolist()]
        for row_values in matrix
    ]


def _read_bool_config_field(
    *,
    transform_object: dict[str, object] | None,
    field_name: str,
    parameter_value: object,
    default_value: bool,
) -> bool:
    """读取布尔配置项。"""

    raw_value = _resolve_transform_field_value(
        transform_object=transform_object,
        field_name=field_name,
        parameter_value=parameter_value,
    )
    if _is_missing_config_value(raw_value):
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _resolve_border_mode(raw_value: object, *, cv2_module) -> int:
    """解析边界填充模式。"""

    if _is_missing_config_value(raw_value):
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

    if _is_missing_config_value(raw_value):
        return 0
    return require_uint8_int(raw_value, field_name="border_value")


def _read_optional_text(raw_value: object, *, field_name: str) -> str | None:
    """读取可选文本参数。"""

    if _is_missing_config_value(raw_value):
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _is_missing_config_value(raw_value: object) -> bool:
    """判断配置值是否为空。"""

    return raw_value is None or raw_value == ""
