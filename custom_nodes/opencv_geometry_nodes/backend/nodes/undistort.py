"""Undistort 节点实现。"""

from __future__ import annotations

from typing import Any

from backend.nodes.core_nodes._logic_node_support import build_value_payload, extract_value_by_path, require_value_payload
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


NODE_TYPE_ID = "custom.opencv.undistort"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按标定参数执行镜头畸变矫正。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _source_object_key, image_matrix = load_image_matrix(request)
    image_height = int(image_matrix.shape[0])
    image_width = int(image_matrix.shape[1])
    config_object, config_source = _resolve_config_object(request)
    camera_matrix = _normalize_matrix3x3(
        _resolve_config_field_value(
            config_object=config_object,
            field_name="camera_matrix",
            parameter_value=request.parameters.get("camera_matrix"),
        ),
        np_module=np_module,
        field_name="camera_matrix",
    )
    distortion_coefficients = _normalize_distortion_coefficients(
        _resolve_config_field_value(
            config_object=config_object,
            field_name="distortion_coefficients",
            parameter_value=request.parameters.get("distortion_coefficients"),
        ),
        np_module=np_module,
    )
    rectify_matrix_value = _resolve_config_field_value(
        config_object=config_object,
        field_name="rectify_matrix",
        parameter_value=request.parameters.get("rectify_matrix"),
    )
    rectify_matrix = (
        _normalize_matrix3x3(rectify_matrix_value, np_module=np_module, field_name="rectify_matrix")
        if rectify_matrix_value is not None and rectify_matrix_value != ""
        else None
    )
    output_width, output_height, output_size_source = _resolve_output_size(
        request,
        config_object=config_object,
        image_width=image_width,
        image_height=image_height,
    )
    use_optimal_new_camera_matrix = _read_bool_config_field(
        config_object=config_object,
        field_name="use_optimal_new_camera_matrix",
        parameter_value=request.parameters.get("use_optimal_new_camera_matrix"),
        default_value=True,
    )
    alpha_value = _read_alpha(
        _resolve_config_field_value(
            config_object=config_object,
            field_name="alpha",
            parameter_value=request.parameters.get("alpha"),
        )
    )
    crop_to_valid_roi = _read_bool_config_field(
        config_object=config_object,
        field_name="crop_to_valid_roi",
        parameter_value=request.parameters.get("crop_to_valid_roi"),
        default_value=False,
    )
    raw_new_camera_matrix = _resolve_config_field_value(
        config_object=config_object,
        field_name="new_camera_matrix",
        parameter_value=request.parameters.get("new_camera_matrix"),
    )

    valid_roi_xywh = [0, 0, int(output_width), int(output_height)]
    new_camera_matrix_source = "camera-matrix"
    if raw_new_camera_matrix is not None and raw_new_camera_matrix != "":
        new_camera_matrix = _normalize_matrix3x3(
            raw_new_camera_matrix,
            np_module=np_module,
            field_name="new_camera_matrix",
        )
        new_camera_matrix_source = "input"
    elif use_optimal_new_camera_matrix:
        optimal_new_camera_matrix, valid_roi = cv2_module.getOptimalNewCameraMatrix(
            camera_matrix,
            distortion_coefficients,
            (image_width, image_height),
            alpha_value,
            (output_width, output_height),
        )
        new_camera_matrix = optimal_new_camera_matrix.astype(np_module.float32, copy=False)
        valid_roi_xywh = [int(valid_roi[0]), int(valid_roi[1]), int(valid_roi[2]), int(valid_roi[3])]
        new_camera_matrix_source = "optimal"
    else:
        new_camera_matrix = camera_matrix.copy()

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

    map_x, map_y = cv2_module.initUndistortRectifyMap(
        camera_matrix,
        distortion_coefficients,
        rectify_matrix,
        new_camera_matrix,
        (output_width, output_height),
        cv2_module.CV_32FC1,
    )
    undistorted_image = cv2_module.remap(
        image_matrix,
        map_x,
        map_y,
        interpolation=interpolation,
        borderMode=border_mode,
        borderValue=border_value_argument,
    )
    cropped_output = False
    if crop_to_valid_roi:
        roi_x, roi_y, roi_width, roi_height = valid_roi_xywh
        if roi_width > 0 and roi_height > 0:
            undistorted_image = undistorted_image[roi_y : roi_y + roi_height, roi_x : roi_x + roi_width]
            cropped_output = True
        else:
            cropped_output = False

    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=undistorted_image,
        error_message="OpenCV undistort 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="undistort",
        output_extension=".png",
        width=int(undistorted_image.shape[1]),
        height=int(undistorted_image.shape[0]),
        media_type="image/png",
    )
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "config_source": config_source,
                "image_width": image_width,
                "image_height": image_height,
                "output_width": int(undistorted_image.shape[1]),
                "output_height": int(undistorted_image.shape[0]),
                "requested_output_width": int(output_width),
                "requested_output_height": int(output_height),
                "output_size_source": output_size_source,
                "distortion_coefficient_count": int(distortion_coefficients.size),
                "use_optimal_new_camera_matrix": use_optimal_new_camera_matrix,
                "new_camera_matrix_source": new_camera_matrix_source,
                "alpha": round(float(alpha_value), 4),
                "crop_to_valid_roi": crop_to_valid_roi,
                "cropped_output": cropped_output,
                "valid_roi_xywh": valid_roi_xywh,
                "rectify_matrix_provided": rectify_matrix is not None,
            }
        ),
    }


def _resolve_config_object(request: WorkflowNodeExecutionRequest) -> tuple[dict[str, object] | None, str]:
    """读取可选动态标定配置对象。"""

    raw_config_payload = request.input_values.get("config")
    if raw_config_payload is None:
        return None, "parameters"
    config_payload = require_value_payload(raw_config_payload, field_name="config")
    config_path = _read_optional_text(request.parameters.get("config_path"), field_name="config_path")
    resolved_value = (
        extract_value_by_path(root=config_payload["value"], path=config_path)
        if config_path is not None
        else config_payload["value"]
    )
    if not isinstance(resolved_value, dict):
        raise InvalidRequestError("undistort 节点的 config 输入必须解析为对象")
    return dict(resolved_value), "input"


def _resolve_config_field_value(
    *,
    config_object: dict[str, object] | None,
    field_name: str,
    parameter_value: object,
) -> object:
    """优先读取 config 输入中的字段，否则回退到节点参数。"""

    if config_object is not None and config_object.get(field_name) is not None:
        return config_object.get(field_name)
    return parameter_value


def _resolve_output_size(
    request: WorkflowNodeExecutionRequest,
    *,
    config_object: dict[str, object] | None,
    image_width: int,
    image_height: int,
) -> tuple[int, int, str]:
    """解析输出尺寸。"""

    raw_output_width = _resolve_config_field_value(
        config_object=config_object,
        field_name="output_width",
        parameter_value=request.parameters.get("output_width"),
    )
    raw_output_height = _resolve_config_field_value(
        config_object=config_object,
        field_name="output_height",
        parameter_value=request.parameters.get("output_height"),
    )
    if raw_output_width in {None, ""} and raw_output_height in {None, ""}:
        return int(image_width), int(image_height), "source-image"
    if raw_output_width in {None, ""}:
        return int(image_width), require_positive_int(raw_output_height, field_name="output_height"), "mixed"
    if raw_output_height in {None, ""}:
        return require_positive_int(raw_output_width, field_name="output_width"), int(image_height), "mixed"
    return (
        require_positive_int(raw_output_width, field_name="output_width"),
        require_positive_int(raw_output_height, field_name="output_height"),
        "config",
    )


def _normalize_matrix3x3(raw_value: object, *, np_module: Any, field_name: str):
    """把 3x3 数值矩阵规范化为 float32 ndarray。"""

    if not isinstance(raw_value, list) or len(raw_value) != 3:
        raise InvalidRequestError(f"{field_name} 必须是 3x3 数值矩阵")
    normalized_rows: list[list[float]] = []
    for row_index, row_value in enumerate(raw_value):
        if not isinstance(row_value, list) or len(row_value) != 3:
            raise InvalidRequestError(f"{field_name}[{row_index}] 必须是长度为 3 的数组")
        normalized_rows.append(
            [
                require_number(cell_value, field_name=f"{field_name}[{row_index}][{column_index}]")
                for column_index, cell_value in enumerate(row_value)
            ]
        )
    return np_module.array(normalized_rows, dtype=np_module.float32)


def _normalize_distortion_coefficients(raw_value: object, *, np_module: Any):
    """规范化畸变系数数组。"""

    flattened_values = _flatten_numeric_values(raw_value, field_name="distortion_coefficients")
    if len(flattened_values) < 4:
        raise InvalidRequestError("distortion_coefficients 至少需要 4 个数值")
    return np_module.array(flattened_values, dtype=np_module.float32)


def _flatten_numeric_values(raw_value: object, *, field_name: str) -> list[float]:
    """把一维或浅层二维数值数组压平。"""

    if not isinstance(raw_value, list) or not raw_value:
        raise InvalidRequestError(f"{field_name} 必须是非空数值数组")
    flattened_values: list[float] = []
    for item_index, item_value in enumerate(raw_value):
        if isinstance(item_value, list):
            if not item_value:
                raise InvalidRequestError(f"{field_name}[{item_index}] 不能为空数组")
            for nested_index, nested_value in enumerate(item_value):
                flattened_values.append(
                    require_number(
                        nested_value,
                        field_name=f"{field_name}[{item_index}][{nested_index}]",
                    )
                )
        else:
            flattened_values.append(require_number(item_value, field_name=f"{field_name}[{item_index}]"))
    return flattened_values


def _read_bool_config_field(
    *,
    config_object: dict[str, object] | None,
    field_name: str,
    parameter_value: object,
    default_value: bool,
) -> bool:
    """读取布尔配置项。"""

    raw_value = _resolve_config_field_value(
        config_object=config_object,
        field_name=field_name,
        parameter_value=parameter_value,
    )
    if raw_value in {None, ""}:
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _read_alpha(raw_value: object) -> float:
    """读取 optimal camera matrix 的 alpha。"""

    if raw_value in {None, ""}:
        return 0.0
    alpha_value = require_number(raw_value, field_name="alpha")
    if alpha_value < 0.0 or alpha_value > 1.0:
        raise InvalidRequestError("alpha 必须在 0 到 1 之间")
    return float(alpha_value)


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


def _read_optional_text(raw_value: object, *, field_name: str) -> str | None:
    """读取可选文本参数。"""

    if raw_value in {None, ""}:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None
