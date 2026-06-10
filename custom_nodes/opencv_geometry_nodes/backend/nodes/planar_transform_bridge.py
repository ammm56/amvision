"""Planar Transform Bridge 节点实现。"""

from __future__ import annotations

import math
from typing import Any

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._roi_node_support import (
    build_roi_payload,
    polygon_area,
    polygon_bbox_xyxy,
    require_roi_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_optional_object_key,
    normalize_resize_interpolation,
    require_opencv_imports,
    require_planar_transform_payload,
    require_positive_int,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.planar-transform-bridge"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 planar-transform.v1 显式桥接为图片 warp 和 ROI 投影输出。"""

    cv2_module, np_module = require_opencv_imports()
    transform_payload = require_planar_transform_payload(request.input_values.get("transform"))
    raw_image_payload = request.input_values.get("image")
    raw_roi_payload = request.input_values.get("roi")
    if raw_image_payload is None and raw_roi_payload is None:
        raise InvalidRequestError(
            "planar-transform-bridge 节点至少要求 image 或 roi 输入之一",
        )

    direction = _read_direction(request.parameters.get("direction"))
    source_role, target_role = _resolve_direction_roles(direction)
    transform_matrix, matrix_source = _resolve_transform_matrix(
        transform_payload,
        direction=direction,
        np_module=np_module,
    )
    source_image_metadata = _read_optional_image_metadata(transform_payload.get(source_role))
    target_image_metadata = _read_optional_image_metadata(transform_payload.get(target_role))

    response_payload: dict[str, object] = {}
    summary_value: dict[str, object] = {
        "direction": direction,
        "source_image_role": source_role,
        "target_image_role": target_role,
        "transform_kind": transform_payload["transform_kind"],
        "matrix_source": matrix_source,
        "match_count": int(transform_payload["match_count"]),
        "inlier_count": int(transform_payload["inlier_count"]),
        "inlier_ratio": round(
            int(transform_payload["inlier_count"]) / int(transform_payload["match_count"]),
            6,
        )
        if int(transform_payload["match_count"]) > 0
        else 0.0,
        "reprojection_error": transform_payload.get("reprojection_error"),
        "image_applied": raw_image_payload is not None,
        "roi_applied": raw_roi_payload is not None,
        "matrix_3x3": _serialize_matrix_3x3(transform_matrix),
    }

    if raw_image_payload is not None:
        image_payload, _source_object_key, image_matrix = load_image_matrix(request)
        _validate_image_dimensions(
            image_payload=image_payload,
            expected_image=source_image_metadata,
            input_name="image",
        )
        (
            output_width,
            output_height,
            output_size_source,
            applied_matrix,
            bounds_summary,
        ) = _resolve_image_output_shape(
            request,
            source_image_width=int(image_matrix.shape[1]),
            source_image_height=int(image_matrix.shape[0]),
            target_image_metadata=target_image_metadata,
            transform_matrix=transform_matrix,
            cv2_module=cv2_module,
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
            (border_value, border_value, border_value)
            if len(image_matrix.shape) == 3
            else border_value
        )
        output_image = cv2_module.warpPerspective(
            image_matrix,
            applied_matrix,
            (output_width, output_height),
            flags=interpolation,
            borderMode=border_mode,
            borderValue=border_value_argument,
        )
        encoded_image = encode_png_image_bytes(
            request,
            image_matrix=output_image,
            error_message="OpenCV planar-transform-bridge 后无法编码输出图片",
        )
        response_payload["image"] = build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="planar-transform-bridge",
            output_extension=".png",
            width=int(output_width),
            height=int(output_height),
            media_type="image/png",
        )
        summary_value.update(
            {
                "source_image_width": int(image_matrix.shape[1]),
                "source_image_height": int(image_matrix.shape[0]),
                "output_width": int(output_width),
                "output_height": int(output_height),
                "output_size_source": output_size_source,
                "fit_output_bounds": bool(request.parameters.get("fit_output_bounds", False)),
                "applied_matrix_3x3": _serialize_matrix_3x3(applied_matrix),
                **bounds_summary,
            }
        )

    if raw_roi_payload is not None:
        roi_payload = require_roi_payload(raw_roi_payload, node_id=request.node_id)
        _validate_roi_dimensions(
            roi_payload=roi_payload,
            expected_image=source_image_metadata,
        )
        projected_roi_payload = _project_roi_payload(
            roi_payload=roi_payload,
            transform_matrix=transform_matrix,
            target_image_metadata=target_image_metadata,
            direction=direction,
            cv2_module=cv2_module,
            np_module=np_module,
            output_roi_id=request.parameters.get("output_roi_id"),
            output_display_name=request.parameters.get("output_display_name"),
        )
        response_payload["roi"] = projected_roi_payload
        summary_value.update(
            {
                "output_roi_id": projected_roi_payload["roi_id"],
                "output_roi_kind": projected_roi_payload["roi_kind"],
                "output_roi_area": int(projected_roi_payload["area"]),
                "output_roi_bbox_xyxy": [round(float(value), 4) for value in projected_roi_payload["bbox_xyxy"]],
            }
        )

    response_payload["summary"] = build_value_payload(summary_value)
    return response_payload


def _read_direction(raw_value: object) -> str:
    """读取投影方向。"""

    if raw_value in {None, ""}:
        return "source-a-to-source-b"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("direction 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"source-a-to-source-b", "source-b-to-source-a"}:
        raise InvalidRequestError("direction 仅支持 source-a-to-source-b 或 source-b-to-source-a")
    return normalized_value


def _resolve_direction_roles(direction: str) -> tuple[str, str]:
    """根据方向解析 transform 中的源图和目标图字段名。"""

    if direction == "source-a-to-source-b":
        return "source_a_image", "source_b_image"
    return "source_b_image", "source_a_image"


def _resolve_transform_matrix(
    transform_payload: dict[str, object],
    *,
    direction: str,
    np_module: Any,
):
    """根据方向选择实际应用的 3x3 变换矩阵。"""

    if direction == "source-a-to-source-b":
        return (
            np_module.array(transform_payload["matrix_3x3"], dtype=np_module.float32),
            "matrix_3x3",
        )

    inverse_matrix_3x3 = transform_payload.get("inverse_matrix_3x3")
    if isinstance(inverse_matrix_3x3, list):
        return np_module.array(inverse_matrix_3x3, dtype=np_module.float32), "inverse_matrix_3x3"

    try:
        computed_inverse = np_module.linalg.inv(
            np_module.array(transform_payload["matrix_3x3"], dtype=np_module.float64)
        )
    except np_module.linalg.LinAlgError as error:
        raise InvalidRequestError(
            "当前 planar-transform 不可逆，无法执行 source-b-to-source-a 桥接",
        ) from error
    return computed_inverse.astype(np_module.float32), "computed-inverse"


def _read_optional_image_metadata(raw_image_payload: object) -> dict[str, object] | None:
    """读取 transform payload 中的可选图片元数据。"""

    if not isinstance(raw_image_payload, dict):
        return None
    return dict(raw_image_payload)


def _validate_image_dimensions(
    *,
    image_payload: dict[str, object],
    expected_image: dict[str, object] | None,
    input_name: str,
) -> None:
    """校验图片输入分辨率是否与 transform 的源图元数据一致。"""

    if expected_image is None:
        return
    expected_width = expected_image.get("width")
    expected_height = expected_image.get("height")
    actual_width = image_payload.get("width")
    actual_height = image_payload.get("height")
    if not isinstance(expected_width, int) or not isinstance(expected_height, int):
        return
    if not isinstance(actual_width, int) or not isinstance(actual_height, int):
        return
    if actual_width != expected_width or actual_height != expected_height:
        raise InvalidRequestError(
            f"planar-transform-bridge 的 {input_name} 分辨率与 transform 源图不一致",
            details={
                "expected_width": expected_width,
                "expected_height": expected_height,
                "actual_width": actual_width,
                "actual_height": actual_height,
            },
        )


def _validate_roi_dimensions(
    *,
    roi_payload: dict[str, object],
    expected_image: dict[str, object] | None,
) -> None:
    """校验 ROI 绑定的源图分辨率是否与 transform 的源图元数据一致。"""

    if expected_image is None:
        return
    roi_source_image = roi_payload.get("source_image")
    if not isinstance(roi_source_image, dict):
        return
    _validate_image_dimensions(
        image_payload=roi_source_image,
        expected_image=expected_image,
        input_name="roi.source_image",
    )


def _resolve_image_output_shape(
    request: WorkflowNodeExecutionRequest,
    *,
    source_image_width: int,
    source_image_height: int,
    target_image_metadata: dict[str, object] | None,
    transform_matrix: Any,
    cv2_module: Any,
    np_module: Any,
) -> tuple[int, int, str, Any, dict[str, object]]:
    """解析桥接后图片的输出尺寸和实际应用矩阵。"""

    fit_output_bounds = _read_optional_bool(request.parameters.get("fit_output_bounds"), default_value=False)
    raw_output_width = request.parameters.get("output_width")
    raw_output_height = request.parameters.get("output_height")
    target_width = (
        int(target_image_metadata["width"])
        if isinstance(target_image_metadata, dict) and isinstance(target_image_metadata.get("width"), int)
        else None
    )
    target_height = (
        int(target_image_metadata["height"])
        if isinstance(target_image_metadata, dict) and isinstance(target_image_metadata.get("height"), int)
        else None
    )

    translated_matrix = transform_matrix.copy()
    fit_bounds_summary: dict[str, object] = {}
    fit_width = None
    fit_height = None
    if fit_output_bounds:
        min_x, min_y, max_x, max_y = _compute_perspective_bounds(
            image_width=source_image_width,
            image_height=source_image_height,
            transform_matrix=transform_matrix,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        translation_offset_x = -min_x if min_x < 0.0 else 0.0
        translation_offset_y = -min_y if min_y < 0.0 else 0.0
        translation_matrix = np_module.array(
            [
                [1.0, 0.0, translation_offset_x],
                [0.0, 1.0, translation_offset_y],
                [0.0, 0.0, 1.0],
            ],
            dtype=np_module.float32,
        )
        translated_matrix = translation_matrix @ transform_matrix
        fit_width = max(1, int(math.ceil(max_x + translation_offset_x)) + 1)
        fit_height = max(1, int(math.ceil(max_y + translation_offset_y)) + 1)
        fit_bounds_summary = {
            "fit_bounds_width": int(fit_width),
            "fit_bounds_height": int(fit_height),
            "translation_offset_x": round(float(translation_offset_x), 4),
            "translation_offset_y": round(float(translation_offset_y), 4),
        }

    if raw_output_width in {None, ""} and raw_output_height in {None, ""}:
        if fit_output_bounds and fit_width is not None and fit_height is not None:
            return fit_width, fit_height, "fit-bounds", translated_matrix, fit_bounds_summary
        if target_width is not None and target_height is not None:
            return target_width, target_height, "transform-target-image", translated_matrix, fit_bounds_summary
        return source_image_width, source_image_height, "source-image", translated_matrix, fit_bounds_summary

    if raw_output_width in {None, ""}:
        fallback_width = fit_width if fit_output_bounds and fit_width is not None else target_width
        if fallback_width is None:
            fallback_width = source_image_width
        return (
            int(fallback_width),
            require_positive_int(raw_output_height, field_name="output_height"),
            "mixed",
            translated_matrix,
            fit_bounds_summary,
        )

    if raw_output_height in {None, ""}:
        fallback_height = fit_height if fit_output_bounds and fit_height is not None else target_height
        if fallback_height is None:
            fallback_height = source_image_height
        return (
            require_positive_int(raw_output_width, field_name="output_width"),
            int(fallback_height),
            "mixed",
            translated_matrix,
            fit_bounds_summary,
        )

    return (
        require_positive_int(raw_output_width, field_name="output_width"),
        require_positive_int(raw_output_height, field_name="output_height"),
        "parameters",
        translated_matrix,
        fit_bounds_summary,
    )


def _compute_perspective_bounds(
    *,
    image_width: int,
    image_height: int,
    transform_matrix: Any,
    cv2_module: Any,
    np_module: Any,
) -> tuple[float, float, float, float]:
    """计算图片四角经过透视变换后的外接范围。"""

    corner_matrix = np_module.array(
        [[[0.0, 0.0]], [[float(image_width - 1), 0.0]], [[float(image_width - 1), float(image_height - 1)]], [[0.0, float(image_height - 1)]]],
        dtype=np_module.float32,
    )
    transformed_corners = cv2_module.perspectiveTransform(corner_matrix, transform_matrix).reshape(-1, 2)
    x_values = transformed_corners[:, 0].tolist()
    y_values = transformed_corners[:, 1].tolist()
    return (
        float(min(x_values)),
        float(min(y_values)),
        float(max(x_values)),
        float(max(y_values)),
    )


def _project_roi_payload(
    *,
    roi_payload: dict[str, object],
    transform_matrix: Any,
    target_image_metadata: dict[str, object] | None,
    direction: str,
    cv2_module: Any,
    np_module: Any,
    output_roi_id: object,
    output_display_name: object,
) -> dict[str, object]:
    """把 ROI polygon 投影到目标坐标系。"""

    polygon_xy = roi_payload["polygon_xy"]
    polygon_matrix = np_module.array(
        [[[float(point[0]), float(point[1])]] for point in polygon_xy],
        dtype=np_module.float32,
    )
    projected_points = cv2_module.perspectiveTransform(polygon_matrix, transform_matrix).reshape(-1, 2)
    projected_polygon_xy: list[list[float]] = []
    for point_x, point_y in projected_points.tolist():
        if not math.isfinite(float(point_x)) or not math.isfinite(float(point_y)):
            raise InvalidRequestError("planar-transform-bridge 输出 ROI 含有无效坐标")
        projected_polygon_xy.append([round(float(point_x), 4), round(float(point_y), 4)])

    projected_area = polygon_area(projected_polygon_xy)
    if projected_area <= 0:
        raise InvalidRequestError("planar-transform-bridge 输出 ROI 面积必须大于 0")

    resolved_roi_id = _resolve_output_roi_id(
        input_roi_id=str(roi_payload["roi_id"]),
        output_roi_id=output_roi_id,
        direction=direction,
    )
    resolved_display_name = _resolve_output_display_name(
        input_display_name=roi_payload.get("display_name"),
        input_roi_id=str(roi_payload["roi_id"]),
        output_display_name=output_display_name,
        direction=direction,
    )
    return build_roi_payload(
        roi_id=resolved_roi_id,
        display_name=resolved_display_name,
        roi_kind="polygon",
        bbox_xyxy=polygon_bbox_xyxy(projected_polygon_xy),
        polygon_xy=projected_polygon_xy,
        area=projected_area,
        source_image=target_image_metadata,
    )


def _resolve_output_roi_id(*, input_roi_id: str, output_roi_id: object, direction: str) -> str:
    """解析输出 ROI ID。"""

    if output_roi_id in {None, ""}:
        suffix = "a2b" if direction == "source-a-to-source-b" else "b2a"
        return f"{input_roi_id}-{suffix}"
    if not isinstance(output_roi_id, str):
        raise InvalidRequestError("output_roi_id 必须是字符串")
    normalized_value = output_roi_id.strip()
    if not normalized_value:
        raise InvalidRequestError("output_roi_id 不能为空字符串")
    return normalized_value


def _resolve_output_display_name(
    *,
    input_display_name: object,
    input_roi_id: str,
    output_display_name: object,
    direction: str,
) -> str | None:
    """解析输出 ROI 显示名。"""

    if output_display_name not in {None, ""}:
        if not isinstance(output_display_name, str):
            raise InvalidRequestError("output_display_name 必须是字符串")
        normalized_value = output_display_name.strip()
        if not normalized_value:
            raise InvalidRequestError("output_display_name 不能为空字符串")
        return normalized_value

    base_name = input_display_name.strip() if isinstance(input_display_name, str) and input_display_name.strip() else input_roi_id
    suffix = "A->B" if direction == "source-a-to-source-b" else "B->A"
    return f"{base_name} {suffix}"


def _serialize_matrix_3x3(matrix: Any) -> list[list[float]]:
    """把 3x3 矩阵规整为可序列化数组。"""

    return [
        [round(float(cell_value), 6) for cell_value in row_values.tolist()]
        for row_values in matrix
    ]


def _read_optional_bool(raw_value: object, *, default_value: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("fit_output_bounds 必须是布尔值")
    return raw_value


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
